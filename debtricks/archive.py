
from __future__ import print_function

import logging
_log = logging.getLogger(__name__)

import os, sys, hashlib, stat, time
from glob import glob
from subprocess import check_call
from tempfile import TemporaryDirectory, SpooledTemporaryFile
from collections import defaultdict
from shutil import copyfileobj

from urllib3 import connection_from_url

from debian.deb822 import Release, Packages

GPG='/usr/bin/gpg2'
# trusted keys for repo Release.gpg
KEYRINGS=glob('/etc/apt/trusted.gpg.d/*.gpg')
# section names in Release
HASHS=['SHA1','SHA256']

__all__ = [
    'Archive',
]

def gpg_verify(content, sig):
    with TemporaryDirectory() as D:
        gpgdir = os.path.join(D,'gpg')
        env = os.environ.copy()
        env['GNUPGHOME'] = gpgdir

        cfile =  os.path.join(D,'file')
        sfile =  os.path.join(D,'sig')
        os.mkdir(gpgdir)

        check_call([GPG, '--import']+KEYRINGS, env=env)
        with open(cfile,'wb') as F:
            F.write(content)
        with open(sfile,'wb') as F:
            F.write(sig)

        check_call([GPG,'--verify',sfile,cfile], env=env)

def proc_release(rel):
    """Extract a dictionary keyed by file name
    with file sizes and hashes
    {'<name>':{'name':'<name>','size':0,'sha1':'xxx','sha256':'xxx',...}}
    """
    info = defaultdict(dict)
    for S in HASHS:
        for ent in rel[S]:
            info[ent['name']].update(ent)

    return info

class SubManifest(object):
    def __init__(self, M, path):
        self._man, self._path = M, path
    def __contains__(self, key):
        return (self._path+key) in self._man
    def get(self, path):
        return self._man.get(self._path+path)
    def getfile(self, path):
        return self._man.getfile(self._path+path)
    def __repr__(self):
        return 'SubManifest(url="%s%s")'%(self._man.path, self._path)

class Manifest(object):
    SubManifest = SubManifest
    def __init__(self, arch, info, path):
        self.arch, self._info, self.path = arch, info, path
    def cd(self, subdir):
        return self.SubManifest(self, subdir)
    def __contains__(self, key):
        return key in self._info
    def get(self, path):
        I = self._info[path]
        fname = self.path+I['name']
        hashme = None
        for H in HASHS:
            H=H.lower()
            if H in I:
                expect = I[H]
                hashme = hashlib.new(H)
        if hashme is None:
            raise RuntimeError("No hash information for '%s'"%(fname))
        content = self.arch.get(fname)
        hashme.update(content)
        if hashme.hexdigest()!=expect:
            raise RuntimeError("Hash mismatch for '%s' %s != %s"%(fname, hashme.hexdigest(),expect))
        return content

    def getfile(self, path):
        I = self._info[path]
        fname = self.path+I['name']
        hashme = None
        for H in HASHS:
            H=H.lower()
            if H in I:
                expect = I[H]
                hashme = H # hash name (eg. 'sha256')
        if hashme is None:
            raise RuntimeError("No hash information for '%s'"%(fname))
        content = self.arch.getfile(fname, hash=hashme, expect=expect,
                                    size=I.get('size'))
        return content
    def __repr__(self):
        return 'Manifest(url="%s")'%(self._man.path,)

class Archive(object):
    """Debian package archive access
    
    >>> repo=Archive('debian','stable')
    >>> 'main' in repo.components
    True
    >>> 'amd64' in repo.archs
    True
    >>> I=repo.installer('amd64')
    >>> 'MANIFEST' in I
    True
    >>> F=I.getfile('netboot/debian-installer/amd64/linux')
    >>> F.tell()==0
    True
    >>> F.seek(0,2)>0
    True
    >>> F.close()
    """
    cachedir = os.path.expanduser('~/.cache/debtricks/')
    region = 'us'
    _urls = {
        'debian':'http://ftp.%(region)s.debian.org/debian/dists/%(release)s/',
        'ubuntu':'http://archive.ubuntu.com/ubuntu/dists/%(release)s/',
    }
    Manifest = Manifest
    def __init__(self, distro=None, release=None, cachedir=None, secure=True):
        if cachedir:
            self.cachedir = cachedir
        os.makedirs(self.cachedir, exist_ok=True)

        self._parts = {'region':self.region, 'distro':distro, 'release':release}
        base = distro
        if not distro.startswith('http'):
            base = self._urls[distro]
        elif not distro.endswith('/'):
            base = base+'/'
        self.baseurl = base%self._parts

        self._pool =  connection_from_url(self.baseurl)
        self._etag = {}
        self._content = {}

        release = self.get('Release')
        if secure:
            release_gpg = self.get('Release.gpg')
            gpg_verify(release, release_gpg)
        else:
            _log.warn('Skipping signature check of RELEASE')

        release = self.release = Release(release)

        self.codename = release['Codename']
        self.archs = set(release['Architectures'].split())
        self.components = set(release['Components'].split())

        info = proc_release(release)

        self._top = self.Manifest(self, info, '')

    def get(self, src):
        """Fetch file and return content as string.
        Use ETag
        """
        url = self.baseurl+src
        headers = {}
        etag = self._etag.get(src)
        if etag:
            assert src in self._content
            headers['If-Match'] = etag
        with self._pool.request('GET', url, headers=headers) as R:
            _log.debug('Fetch %s with %s -> %d', url, headers, R.status)
            if R.status==304:
                return self._content[src]
            elif R.status==200:
                ret = R.data
                etag = etag and R.headers.get('ETag')
                if etag:
                    self.debug('Keep etag %s', etag)
                    self._content[src] = ret
                    self._etag[src] = etag
                return ret
            else:
                raise RuntimeError('Failed to fetch "%s" -> %d'%(url,R.status))

    def getfile(self, src, hash=None, expect=None, size=None):
        """Fetch file as file-like object
        Use Modified
        """
        url = self.baseurl+src
        headers = {}
        cachefile = os.path.join(self.cachedir, url.replace('/','_'))
        try:
            F = open(cachefile, 'r+b')
        except FileNotFoundError:
            F = open(cachefile, 'w+b')
        else:
            try:
                H = hashlib.new(hash)
                for chunk in iter(lambda:F.read(16384), b''):
                    H.update(chunk)
                F.seek(0)
                if H.hexdigest()==expect and (size is None or size==F.tell()):
                    _log.info('Cache hit for %s', url)
                    return F
                else:
                    _log.info('Cache miss for %s', url)
            except:
                F.close()
                raise

        try:
            F.truncate(0)
            H = hashlib.new(hash)

            with self._pool.request('GET', url, headers={}, preload_content=False) as R:
                if R.status!=200:
                    raise RuntimeError("Failed to fetch %s"%url)
                for chunk in R.stream(16384):
                    H.update(chunk)
                    F.write(chunk)

            if H.hexdigest()==expect and (size is None or size==F.tell()):
                F.seek(0)
                _log.info('Fetch complete for %s', url)
                return F
        except:
            F.close()
            raise

    def installer(self, arch, rev='current'):
        prefix = "main/installer-%s/%s/images/"%(arch, rev)
        M = self._top.get(prefix+"SHA256SUMS").decode('ascii')
        ret = {}
        for L in M.splitlines():
            H, N = L.split(None,1)
            if N.startswith('./'):
                N = N[2:]
            ret[N] = {'name':N,'sha256':H}
        return self.Manifest(self, ret, prefix)

    def section(self, arch, name):
        if name not in self.components:
            raise ValueError("Invalid components name '%s'"%name)
        if arch=='source':
            fname = '%s/source/Source'%name
        else:
            fname = '%s/binary-%s/Packages'%(name,arch)

        for suf in ('.gz','.xz','.bz2',''):
            fullname = fname+suf
            if fullname not in self._top:
                continue
            with self._top.getfile(fullname) as F:
                info = {}
                for pkg in Packages.iter_paragraphs(F, use_apt_pkg=True):
                    info[pkg['Package']] = pkg
            return info
        raise RuntimeError("Package listing not available with any known suffix")

if __name__=='__main__':
    logging.basicConfig(level=logging.DEBUG)
    import doctest
    doctest.testmod()
