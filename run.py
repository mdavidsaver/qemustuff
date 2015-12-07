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

    P = argparse.ArgumentParser(description='Run VM image')
    P.add_argument('image', metavar='NAME', help='VM image file name')
    P.add_argument('qemuargs', nargs='*')
    P.add_argument('-p','--port', metavar='INT', type=int, default=5990, help='SPICE display port')
    P.add_argument('-l','--lvl',metavar='NAME',default='INFO',help='python log level', type=lvl)

    A = P.parse_args()
    M = re.match(r'([^-]+)-([^.]+).img', A.image)
    if not M:
        P.error('incorrect image name format.  Must be "name-arch.img"')
    elif not os.path.isfile(A.image):
        P.error('%s not a file'%A.image)
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
    
    exe = shutil.which('qemu-system-%s'%deb2qemu[A.arch])
    if not exe:
        _log.error('Failed to find emulator for %s', deb2qemu[A.arch])
        sys.exit(1)

    args = [exe]
    _log.warn('SPICE port %d', A.port)
    args += '-m 1024 -enable-kvm -vga qxl -usbdevice tablet'.split(' ')
    args += ['-display', 'none']
    args += ['-chardev','socket,id=monitor,path=%s,server,nowait'%(A.image+".sock")]
    args += ['-monitor','chardev:monitor']
    args += ['-spice', 'addr=127.0.0.1,port=%d,ipv4,disable-ticketing'%A.port] # TODO password=
    args += ['-device', 'virtio-serial-pci']
    args += ['-device', 'virtserialport,chardev=spicechannel0,name=com.redhat.spice.0']
    args += ['-chardev', 'spicevmc,id=spicechannel0,name=vdagent']
    args += ['-drive', 'file=%s,aio=native,cache=writethrough'%A.image]
    args += ['-net', 'nic', '-net', 'user,smb=%s'%os.path.expanduser('~')]

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
