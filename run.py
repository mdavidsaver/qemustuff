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
            raise argparse.ArgumentTypeError('invalid log level %s'%A.lvl)
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
    P.add_argument('-D','--display',metavar='spice|X',default='X',help='Display method')
    P.add_argument('--unsafe',action='store_true',default=False,help='Unsafe, but faster, disck caching')
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

    args = [exe]
    _log.warn('SPICE port %d', A.port)
    args += ['-m','%d'%A.mem, '-usbdevice', 'tablet']
    args += ['-device', 'virtio-serial-pci']
    if A.display=='spice':
        # unix socket for monitor console
        args += ['-chardev','socket,id=monitor,path=%s,server,nowait'%(A.image+".mon")]
        args += ['-monitor','chardev:monitor']
        # spice
        args += ['-display','none']
        args += ['-spice', 'addr=127.0.0.1,port=%d,ipv4,disable-ticketing'%A.port] # TODO password=
        args += ['-device', 'virtserialport,chardev=spicechannel0,name=com.redhat.spice.0']
        args += ['-chardev', 'spicevmc,id=spicechannel0,name=vdagent']
    elif A.display=='X':
        pass
    else:
        _log.error("Unknown display method %s", A.display)
    # guest agent
    args += ['-chardev', 'socket,path=%s,server,nowait,id=agent'%(A.ga,),
             '-device', 'virtserialport,chardev=agent,name=org.qemu.guest_agent.0']
    # disk
    if not A.unsafe:
        args += ['-drive', 'file=%s,index=0,media=disk'%A.image]
    else:
        args += ['-drive', 'file=%s,index=0,media=disk,aio=native,cache=unsafe,cache.direct=on'%A.image]
    # net
    net = ['user','smb=%s'%os.path.expanduser('~')]
    net.extend(A.net)
    args += ['-net', 'nic', '-net', ','.join(net)]

    if A.smp>1:
        args += ['-smp','cpus=%d'%A.smp]

    if A.arch==hostarch() or (A.arch=='i386' and hostarch()=='amd64'):
        args += ['-enable-kvm']

    if A.arch!='powerpc':
        args += ['-vga','qxl']

    args += A.qemuargs

    _log.debug('Invoke: %s', ' '.join(args))

    _log.info('Run emulator')
    from subprocess import check_call
    check_call(args)

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
