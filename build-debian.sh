#!/bin/sh
set -e -x

die() {
    echo "$1" >&2
    exit 1
}

DIST=$1
shift
ARCH=$1
shift

[ "$DIST" -a "$ARCH" ] || die "Usage: $0 <debdist> <debarch>"

[ -f "preseed/$DIST/preseed.cfg" ] || die "No pre-seed file for $DIST"

#HOSTARCH=`dpkg-architecture -qDEB_HOST_ARCH`

# Map debian arch names to qemu arch names
case "$ARCH" in
amd64) QARGS="--arch=x86_64 --virt-type kvm"; break;;
i386) QARGS="--arch=i386 --virt-type kvm"; break;;
#armhf) QARGS="--arch=armv7l"; break;;
*) die "Unsupported arch $ARCH";;
esac

virt-install \
$QARGS \
--name "$DIST-$ARCH" \
--ram 2047 \
--vcpu=4 \
--os-type=linux \
--os-variant=debianwheezy \
--location="http://ftp.us.debian.org/debian/dists/$DIST/main/installer-$ARCH" \
--initrd-inject="preseed/$DIST/preseed.cfg" \
--extra-args="auto file=/preseed.cfg priority=critical" \
--disk pool=default,size=5,format=qcow2 \
-w user \
--graphics vnc,listen=127.0.0.1 \
--noreboot "$@"
