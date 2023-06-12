#!/usr/bin/env python3

import logging
_log = logging.getLogger(__name__)

import os, sys, re
import shutil

def getargs():
    import argparse
    def lvl(name):
        L = logging.getLevelName(name)
        if type(L)!=int:
            raise argparse.ArgumentTypeError('invalid log level '+name)
        return L

    def isfile(name):
        if not os.path.isfile(name):
            raise argparse.ArgumentTypeError('file does not exist %s'%name)
        return name

    P = argparse.ArgumentParser(description='Run VM image')
    P.add_argument('image', metavar='NAME', help='VM image file name', type=isfile)
    P.add_argument('qemuargs', nargs=argparse.REMAINDER)
    P.add_argument('-p','--port', metavar='INT', type=int, default=5990, help='SPICE display port')
    P.add_argument('-l','--lvl',metavar='NAME',default='INFO',help='python log level', type=lvl)
    P.add_argument('-j','--smp',metavar='NUM',default=0,help='Number of vCPUs', type=int)
    P.add_argument('-m','--mem',metavar='NUM',default=1024,help='RAM size in MB', type=int)
    P.add_argument('-N','--net',metavar='STR',default=[],action='append',help='Additional options for -net user')
    P.add_argument('--isolate',action='store_true')
    P.add_argument('-D','--display',metavar='spice|X',default='X',help='Display method')
    P.add_argument('--ga',metavar='SOCK',help='path for unix socket of guest agent')
    P.add_argument('--mon',metavar='SOCK',help='path for unix socket of monitor')
    P.add_argument('--exe',metavar='PATH',help='Use specific QEMU executable')

    A = P.parse_args()
    M = re.match(r'(.+)-([^.-]+).img', A.image)
    if not M:
        P.error('incorrect image name format.  Must be "name-arch.img"')
    elif not os.path.isfile(A.image):
        P.error('%s not a file'%A.image)
    if not A.ga:
        A.ga = A.image+'.sock'
    if not A.mon:
        A.mon = A.image+'.mon'
    A.name = M.group(1)
    A.arch = M.group(2)
    return A

# arch. name mapping from debian to qemu conventions
deb2qemu = {
    'i386':'i386',
    'amd64':'x86_64',
    'powerpc':'ppc',
}

def hostarch():
    import platform, re
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

    _log.warn('SPICE port %d', A.port)
    args = [
        exe,
        '-M', 'q35',
        '-m','%d'%A.mem,
        '-device', 'intel-iommu',
        '-usbdevice', 'tablet',
        '-device', 'virtio-balloon',
        '-device', 'virtio-rng-pci,rng=rng0',
        '-object', 'rng-random,id=rng0,filename=/dev/urandom',
        '-drive', 'file=%s,index=0,media=disk'%A.image,
        #'-fw_cfg', 'name=mdtest,string=hello', # modprobe qemu_fw_cfg | ls /sys/firmware/qemu_fw_cfg
        '-virtfs', 'local,security_model=none,mount_tag=home,path=%s'%os.path.expanduser('~'),
        '-device', 'virtio-serial-pci',
    ]
    if A.display=='spice':
        args += [
            # unix socket for monitor console
            '-chardev','socket,id=monitor,path=%s,server=on,wait=off'%(A.image+".mon"),
            '-monitor','chardev:monitor',
            # spice
            '-display','none',
            '-spice', 'addr=127.0.0.1,port=%d,ipv4=on,disable-ticketing=on'%A.port, # TODO password=
            '-device', 'virtserialport,chardev=spicechannel0,name=com.redhat.spice.0',
            '-chardev', 'spicevmc,id=spicechannel0,name=vdagent',
        ]
    elif A.display=='X':
        pass
    else:
        _log.error("Unknown display method %s", A.display)
    # guest agent
    args += [
        '-chardev', 'socket,path=%s,server=on,wait=off,id=agent'%(A.ga,),
        '-device', 'virtserialport,chardev=agent,name=org.qemu.guest_agent.0',
    ]
    # net
    net = ['user','smb=%s'%os.path.expanduser('~')]
    if A.isolate:
        net.append('restrict=on')
    net.extend(A.net)
    args += [
        '-net', 'nic,model=e1000',
        '-net', ','.join(net),
    ]

    if A.smp>1:
        args += ['-smp','cpus=%d'%A.smp]

    if A.arch==hostarch() or (A.arch=='i386' and hostarch()=='amd64'):
        args += ['-enable-kvm']

    if A.arch!='powerpc':
        args += ['-vga','qxl', '-cpu', 'host,hv_vpindex,hv_runtime,hv_synic,hv_stimer,hv_reset,hv_time,hv_relaxed']

    args += A.qemuargs

    _log.debug('Invoke: %s', ' '.join(args))

    _log.info('Run emulator')
    from subprocess import check_call, call
    try:
        if A.display=='spice':
            call("spicy -p %d &"%A.port, shell=True)
        check_call(args)

    finally:
        try:
            os.remove(A.image+".sock")
        except OSError as e:
            if e.errno!=2:
                raise
        try:
            os.remove(A.image+".mon")
        except OSError as e:
            if e.errno!=2:
                raise

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
