#!/bin/sh
set -x -e

[ -f test.img ] || qemu-img create -f qcow2 test.img 5G

exec qemu-system-arm -m 1024 -M versatilepb \
-kernel vmlinuz-3.16.0-4-versatile -initrd initrd.gz \
-drive file=test.img,aio=native \
-serial stdio -vga none

#-append "root=/dev/sda2 rw panic=1 console=ttyAMA0" \
