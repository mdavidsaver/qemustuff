#!/usr/bin/env python3
"""
Debian VM image builder for QEMU/KVM

Automatically downloads and runs the netboot installer with qemu system emulator.
An optional preseed file can be given for automatic install.

The preseed file is loaded via. TFTP (supported by d-i as per debian bug #509723)
"""

import logging
_log = logging.getLogger(__name__)

import os, sys
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

    P = argparse.ArgumentParser(description='Populate Debian vm image')
    P.add_argument('image', metavar='FILE', help='VM image file name', type=isfile)
    P.add_argument('-a','--arch',metavar='NAME', default='host', help='Debian arch. name')
    P.add_argument('-d','--dist',metavar='NAME', default='jessie', help='Debian code name')
    P.add_argument('-P','--preseed',metavar='FILE',help='Debian pre-seed file', type=isfile)
    P.add_argument('--cache',metavar='DIR',default=os.path.join(os.getcwd(),'bcache'))
    P.add_argument('--baseurl',metavar='URL',default='http://ftp.us.debian.org/debian/dists/')
    P.add_argument('-l','--lvl',metavar='NAME',default='INFO',help='python log level', type=lvl)
    return P.parse_args()

# arch. name mapping from debian to qemu conventions
deb2qemu = {
    'i386':'i386',
    'amd64':'x86_64',
}

class Builder(object):
    def __init__(self, args):
        self.args = args
        self.arch = args.arch
        if args.arch=='host':
            import platform, re
            if re.match(r'i.86', platform.machine()):
                self.arch = 'i386'
            elif 'x86_64'==platform.machine():
                self.arch = 'amd64'
            else:
                raise RuntimeError('Unable to detect host arch (%s), use --arch to give explicitly'%platform.machine())

        os.makedirs(args.cache, exist_ok=True)

        self.baseurl = args.baseurl
        if self.baseurl[-1]!='/':
            self.baseurl = self.baseurl+'/'
        # eg. http://ftp.us.debian.org/debian/dists/jessie/main/installer-i386/current/images/netboot/debian-installer/i386/
        self.baseurl = '%s%s/main/installer-%s/current/images/netboot/debian-installer/%s/'%(self.baseurl, args.dist, self.arch, self.arch)
        _log.info('Fetching from %s', self.baseurl)

    def getfile(self, fname, subdir=''):
        """Fetch a file if not in local cache
        """
        _log.info('Fetch %s', fname)
        from urllib.request import urlopen, Request
        from urllib.error import HTTPError
        from time import strftime, gmtime
        url = '%s%s%s'%(self.baseurl, subdir, fname)
        _log.debug(' from %s', url)
        cachename = os.path.join(self.args.cache, url.replace('/','_'))
        _log.debug(' cache as %s', cachename)
        H = {}
        try:
            S = os.stat(cachename)
            #Note: there is the possibility of a race if the file is updated
            #      while being downloaded.  But this seems unlikely...
            H['If-Modified-Since'] = strftime('%a, %d %b %Y %H:%M:%S GMT',
                                              gmtime(S.st_mtime))
        except FileNotFoundError:
            pass

        try:
            R = urlopen(Request(url, headers=H), timeout=10)
            assert R.getcode()==200, R.getcode()
            _log.debug('info: %s', R.info())
            with open(cachename, 'wb') as F:
                while True:
                    D = R.read(16*1024)
                    if len(D)==0:
                        break
                    F.write(D)
                _log.info(' downloaded %d bytes', F.tell())
            R.close()
        except HTTPError as e:
            if e.code==304: # not modified
                _log.info(' using cached copy')
            else:
                raise

        shutil.copyfile(cachename, os.path.join(self.workdir, fname))

    def run(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as D:
            self.workdir = D
            _log.debug('working in %s', self.workdir)

            self.getfile('pxelinux.0')
            self.getfile('ldlinux.c32', subdir='boot-screens/')
            self.getfile('linux')
            self.getfile('initrd.gz')
            os.mkdir(os.path.join(self.workdir, 'pxelinux.cfg'))

            PS = False
            if self.args.preseed:
                shutil.copyfile(self.args.preseed, os.path.join(self.workdir, 'preseed.cfg'))
                PS = True

            with open(os.path.join(self.workdir, 'pxelinux.cfg', 'default'), 'w') as F:
                F.write("label default\nkernel linux\nappend initrd=initrd.gz")
                if PS:
                    F.write(" auto=true priority=critical preseed/url=tftp://10.0.2.2/preseed.cfg --- quiet")
                F.write("\ndefault default\nprompt 1\ntimeout 30\n")

            exe = shutil.which('qemu-system-%s'%deb2qemu[self.arch])
            if not exe:
                _log.error('Failed to find emulator for %s', deb2qemu[self.arch])
                sys.exit(1)

            _log.debug('emulator %s', exe)

            args = [exe]
            args += '-boot order=n -m 1024 -no-reboot -enable-kvm -vga qxl -usbdevice tablet'.split(' ')
            args += ['-drive', 'file=%s,aio=native,cache=writethrough'%self.args.image]
            args += ['-net', 'nic', '-net', 'user,tftp=%s,bootfile=/pxelinux.0'%self.workdir]
            _log.debug('Invoke: %s', ' '.join(args))

            _log.info('Run emulator')
            from subprocess import check_call
            check_call(args)
            _log.info('Success')

if __name__=='__main__':
    A = getargs()
    logging.basicConfig(level=A.lvl)
    try:
        B = Builder(A)
        B.run()
    except:
        _log.exception('unhandled exception')
        sys.exit(1)
