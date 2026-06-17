#!/usr/bin/env python3

import logging
_log = logging.getLogger(__name__)

import os, sys, re
import shutil
from subprocess import check_call, call
from contextlib import ExitStack
from pathlib import Path

def getargs():
    import argparse
    def lvl(name):
        L = logging.getLevelName(name)
        if type(L)!=int:
            raise argparse.ArgumentTypeError('invalid log level '+name)
        return L

    def isfile(name):
        name = Path(name)
        if not name.is_file():
            raise argparse.ArgumentTypeError('file does not exist %s'%name)
        return name

    P = argparse.ArgumentParser(description='Run VM image')
    P.add_argument('image', metavar='NAME', help='VM image file name', type=isfile)
    P.add_argument('qemuargs', nargs=argparse.REMAINDER)
    P.add_argument('-p','--port', metavar='INT', type=int, default=5990, help='SPICE display port')
    P.add_argument('-l','--lvl',metavar='NAME',default='INFO',help='python log level', type=lvl)
    P.add_argument('-j','--smp',metavar='NUM',default=1,help='Number of vCPUs', type=int)
    P.add_argument('-m','--mem',metavar='NUM',default=4196,help='RAM size in MB', type=int)
    P.add_argument('-M','--mount',metavar='NAME:PATH',action='append',default=[],
                   help='virtfs paths to export')
    P.add_argument('-N','--net',metavar='STR',default=[],action='append',help='Additional options for -net user')
    P.add_argument('--isolate',action='store_true')
    P.add_argument('-D','--display',metavar='spice|X|gl|none',default='X',help='Display method')
    P.add_argument('--ga',metavar='SOCK',help='path for unix socket of guest agent')
    P.add_argument('--mon',metavar='SOCK',help='path for unix socket of monitor')
    P.add_argument('--exe',metavar='PATH',help='Use specific QEMU executable')

    A = P.parse_args()
    try:
        A.name, A.arch = A.image.stem.rsplit('-',1)
    except TypeError:
        P.error('incorrect image name format.  Must be "name-arch.img"')
    if not A.ga:
        A.ga = A.image.with_suffix('.sock')
    if not A.mon:
        A.mon = A.image.with_suffix('.mon')
    return A

# arch. name mapping from debian to qemu conventions
deb2qemu = {
    'i386':'i386',
    'amd64':'x86_64',
    'powerpc':'ppc',
    'arm64':'aarch64',
}

def hostarch():
    import platform
    if re.match(r'i.86', platform.machine()):
        return 'i386'
    elif 'x86_64'==platform.machine():
        return 'amd64'
    elif 'ppc'==platform.machine():
        return 'powerpc'
    else:
        raise RuntimeError('Unable to detect host arch (%s)'%platform.machine())

def main(A):
    _log.debug('Args: %s', A)

    exe = A.exe or shutil.which('qemu-system-%s'%deb2qemu[A.arch])
    if not exe:
        _log.error('Failed to find emulator for %s', deb2qemu[A.arch])
        sys.exit(1)

    # https://www.qemu.org/docs/master/system/qemu-manpage.html
    _log.warn('SPICE port %d', A.port)
    args = [
        exe,
        '-M', 'q35,accel=kvm:tcg',
        '-device', 'intel-iommu', # requires q35
        '-m','%d'%A.mem,
        '-smp','cpus=%d'%A.smp,
        '-usbdevice', 'tablet',
        '-parallel', 'none',
        '-device', 'virtio-balloon',
        '-device', 'virtio-rng-pci,rng=rng0',
        '-object', 'rng-random,id=rng0,filename=/dev/urandom',
        '-drive', 'if=virtio,file=%s,index=0,media=disk'%A.image,
        #'-fw_cfg', 'name=mdtest,string=hello', # modprobe qemu_fw_cfg | ls /sys/firmware/qemu_fw_cfg
        '-device', 'virtio-serial-pci',
        # guest agent
        '-chardev', 'socket,path=%s,server=on,wait=off,id=agent'%(A.ga,),
        '-device', 'virtserialport,chardev=agent,name=org.qemu.guest_agent.0',
    ]

    if A.arch==hostarch():
        # https://www.qemu.org/docs/master/system/i386/cpu.html
        args += ['-cpu', 'host']

    for mnt in A.mount:
        mname, mpath = mnt.split(':', 1)
        mpath = os.path.expanduser(mpath)
        args += ['-virtfs', f'local,security_model=none,mount_tag={mname},path={mpath}']

    if A.display=='spice':
        args += [
            '-vga','qxl',
            # unix socket for monitor console
            '-chardev','socket,id=monitor,path=%s,server=on,wait=off'%(A.mon),
            '-monitor','chardev:monitor',
            # spice
            '-display','none',
            '-spice', 'addr=127.0.0.1,port=%d,ipv4=on,disable-ticketing=on'%A.port,
            '-device', 'virtserialport,chardev=spicechannel0,name=com.redhat.spice.0',
            '-chardev', 'spicevmc,id=spicechannel0,name=vdagent',
        ]
    elif A.display=='X':
        args += [
            '-vga','virtio',
            '-display', 'gtk,zoom-to-fit=on',
        ]
    elif A.display=='gl':
        # https://www.qemu.org/docs/master/system/devices/virtio/virtio-gpu.html
        args += [
            '-vga', 'none',
            '-device', 'virtio-vga-gl',
            '-display', 'gtk,zoom-to-fit=on,gl=on',
        ]
    elif A.display=='none':
        args += ['-vga', 'none']
    else:
        _log.error("Unknown display method %s", A.display)

    # net
    # https://www.qemu.org/docs/master/system/devices/net.html
    net = ['user']
    if A.isolate:
        net.append('restrict=on')
    net.extend(A.net)
    args += [
        '-net', 'nic,model=virtio',
        '-net', ','.join(net),
    ]

    args += A.qemuargs

    _log.info('Invoke: %s', ' '.join(args))

    _log.info('Run emulator')
    with ExitStack() as cleaner:
        cleaner.callback(A.ga.unlink, missing_ok=True)
        cleaner.callback(A.mon.unlink, missing_ok=True)

        if A.display=='spice':
            call("spicy -p %d &"%A.port, shell=True)
        check_call(args)

if __name__=='__main__':
    A = getargs()
    logging.basicConfig(level=A.lvl)
    try:
        main(A)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        pass
    except:
        _log.exception('unhandled exception')
        sys.exit(1)
