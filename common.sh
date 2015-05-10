#!/bin/sh
set -e -x

die() {
  echo "$1" >&2
  exit 1
}

NAME=`basename $0`
NAME=${NAME%.sh}

## Better performance when creating an image
# qemu-img create -f qcow2 -o cluster_size=2M,preallocation=metadata "jessie-i386.img" 20G

cd `dirname $0`

case "$NAME" in
*-i386)
  ARCH=i386
  ;;
*-amd64)
  ARCH=x86_64
  ;;
*) die "Unknown arch in $BASE";;
esac

[ -e "$NAME.img" ] || die "Missing image: qemu-img create -f qcow2 \"$NAME.img\" 10G"

exec qemu-system-$ARCH -name "$NAME" \
 -no-reboot -smp 2 -m 2047 -enable-kvm \
 -vga qxl -usbdevice tablet \
 -net nic -net user,smb=$HOME \
 -drive file="$NAME.img",aio=native,cache=writethrough \
 "$@"
