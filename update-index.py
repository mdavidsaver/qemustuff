#!/usr/bin/env python
"""Update a virt-builder index file
"""

import hashlib, os, stat
from cStringIO import StringIO
from ConfigParser import (SafeConfigParser as ConfigParser,
                          NoOptionError)

import guestfs

def getargs():
    import argparse
    P=argparse.ArgumentParser()
    P.add_argument('indexfile')
    P.add_argument('imagefile')
    P.add_argument('-C','--conf')
    return P.parse_args()

def readconf(fname):
    P = ConfigParser()
    if os.path.isfile(fname):
        with open(fname, 'r') as F:
            P.readfp(F)
    return P

def writeconf(fname, P):
    IO = StringIO()
    P.write(IO)
    # the virt-builder's parser is quite particular about whitespace
    val = IO.getvalue().replace(' = ','=')
    outname = fname+'.tmp'
    with open(outname, 'w') as F:
        F.write(val)
    os.rename(outname, fname)

class Processor(object):
    def __init__(self, args):
        self.args = args
        # Read any existing config
        self.C = readconf(args.indexfile)
        # Open the image file
        self.openimg(args.imagefile)
        # Find the output section name and
        self.S = self.get_name()
        print 'Section', self.S
        # create/update section for this iamge
        self.fill_section(self.S)
        # Write out updated file
        writeconf(args.indexfile, self.C)

    def hashimg(self, fname):
        #self.h512 = 'testingXYZ'
        #return

        h512 = hashlib.sha512()
        N, rsize = 0, self.rsize
        with open(fname, 'rb') as F:
            while True:
                buf = F.read(1024*1024)
                if not buf:
                    break
                h512.update(buf)
                N += len(buf)
                print '\r%d/%d (%.1f %%)'%(N,rsize, 100.*N/rsize),
        print 'Done hashing                         '
        self.h512 = h512.hexdigest()

    def openimg(self, imagefile):
        self.rsize = os.stat(imagefile).st_size # on disk size
        H=guestfs.GuestFS(python_return_dict=True)
        self.fmt = H.disk_format(imagefile)
        self.vsize = H.disk_virtual_size(imagefile) # real size

        H.add_drive_ro(imagefile)

        H.launch()
        rootpart=None
        for part in H.inspect_os():
            mtab = H.inspect_get_mountpoints(part)
            if '/' not in mtab:
                continue
            assert mtab['/']==part,(mtab, part)
            rootpart = part
            break

        assert rootpart, "Failed to find root partition"
        self.H, self.rootpart = H, rootpart

    def get_name(self):
        'Find section name'
        if self.args.conf:
            print 'User defines section name'
            return self.args.conf # caller gave a section name

        for S in self.C.sections():
            if not self.C.has_option(S,'file'):
                continue
            if self.args.imagefile == self.C.get(S,'file'):
                print 'Found existing section name for this image'
                return S # use this section if the file name matches

        print 'Deriving section name from image OS'
        dist = self.H.inspect_get_distro(self.rootpart)
        dver = self.H.inspect_get_product_name(self.rootpart)
        return dist+dver # eg. "debian7.8"

    def fill_section(self, S):
        if not self.C.has_section(S):
            self.C.add_section(S)
        self.C.set(S, 'name', self.getopt('name') or S)
        self.C.set(S, 'osinfo', self.getopt('osinfo') or S)
        self.C.set(S, 'arch', self.H.inspect_get_arch(self.rootpart))
        self.C.set(S, 'file', self.args.imagefile)
        self.C.set(S, 'format', self.fmt)
        self.C.set(S, 'size', str(self.vsize))
        self.C.set(S, 'compressed_size', str(self.rsize))
        self.C.set(S, 'expand', self.rootpart)
        notes = self.getopt('notes')
        if notes:
            self.C.set(S, 'notes', notes)

        # waited as long as possible, but need to hash the image file
        # this will take a long time...
        self.hashimg(self.args.imagefile)
        self.C.set(S, 'checksum[sha512]', self.h512)

    def getopt(self, name, dft=None):
        if name in self.args:
            print 'User provided option',name
            return getattr(self.args, name)
        try:
            print 'Using existing value for option',name
            return self.C.get(self.S, name)
        except NoOptionError:
            print 'Using default value for option',name
            return dft

if __name__=='__main__':
    Processor(getargs())
