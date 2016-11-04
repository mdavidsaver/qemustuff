#!/bin/sh
set -e -x
# Create an initramfs image with some basic tools
# found on the host system (including the running kernel)
#  needs: busybox cifs-utils

# re-exec myself w/ fakeroot
[ `id -u` -ne 0 ] && exec fakeroot $0 "$@"

die() {
  echo "$1"
  exit 1
}

[ -x /sbin/mount.cifs ] || die "Missing cifs-utils"
[ -x /usr/bin/strace ] || die "Missing strace"
[ -x /bin/busybox ] || die "Missing busybox"

# So that 'which' will find things
PATH=/sbin:/usr/sbin:$PATH

[ "$1" ] || die "Usage: $0 <linux> <output.gz>"
kernfile="$PWD/$1"
shift
initfile="$PWD/$1"
shift

# we do everything in a temp directory which is cleaned up automatically
SCRATCH=`mktemp -d`
trap "rm -rf '$SCRATCH'; echo cleanup $SCRATCH" EXIT TERM INT QUIT
echo "Working in $SCRATCH"
cd "$SCRATCH"

HARCH=`dpkg-architecture -q DEB_HOST_MULTIARCH`

mkdir image
cd image

# copy a shared library if needed
copylib() {
  lib="$1"
  [ "$lib" ] || return 0
  ldir="$(dirname "$lib")"
  ldir="${ldir#/}"
  install -d "$ldir"
  [ -e "${lib#/}" ] && return 0
  echo "copy in $lib"
  cp "$lib" "$ldir"
}

echo "get ld-linux.so"
ldd /bin/sh | awk '/ld-linux/ { print $1 }' | while read lib; do copylib $lib; done

# copy a binary executable and any required shared libraries
getbin() {
  name="bin/$(basename "$1")"
  cp "$1" "$name"
  echo "copy in $name"
  ldd "$name" | awk '/=>/ { print $3 }' | while read lib; do copylib $lib; done
}

getfile() {
  install -d "$(dirname "$PWD/$1")"
  cp -arP $1 $PWD/$1
  echo "copy in $1"
}

install -d bin
echo "Copy in system executables"
getbin `which busybox`
getbin `which strace`
getbin `which mount.cifs`

getbin /sbin/ethtool

getbin /usr/bin/lspci
getbin /usr/bin/pcimodules
getfile /usr/share/misc/pci.ids

getbin /sbin/dhclient
getbin /sbin/dhclient-script
getfile /etc/dhcp/dhclient-*-hooks.d
install -d var/lib/dhcp

if [ -x /usr/bin/ipmitool ]; then
  getbin /usr/bin/ipmitool
  getfile /usr/share/ipmitool
fi

#echo "Copy in python2.7"
#getbin `which python2.7`
#install -d usr/lib
#rsync -av --exclude 'dist-*' --exclude 'site-*' /usr/lib/python2.7 usr/lib/
#ln -Ts python2.7 bin/python

echo "Copy in kernel modules"
KVER=`uname -r`
install -d "lib/modules/$KVER/kernel"

[ /boot/vmliinuz-$KVER ] || die "Missing kernel image for $KVER"

cat << EOF > ../mod.make
include \$(KDIR)/modules.dep

%.ko:
	[ -d \$(dir \$@) ] || install -d \$(dir \$@)
	cp -a \$(KDIR)/\$@ \$@
EOF

for nn in modules.order modules.builtin
do
  cp "/lib/modules/$KVER/$nn" "lib/modules/$KVER/$nn"
done

for kd in arch crypto fs lib mm net/core net/ipv4 net/ipv6 net/unix drivers/ata drivers/scsi drivers/virtio drivers/net/ethernet \
 drivers/char/ipmi drivers/acpi
do
  install -d "$(dirname "lib/modules/$KVER/kernel/$kd")"
  rsync -a "/lib/modules/$KVER/kernel/$kd/" "lib/modules/$KVER/kernel/$kd"
done

(cd "lib/modules/$KVER" && find kernel -name '*.ko' | xargs \
make -f ../../../../mod.make KDIR="/lib/modules/$KVER"  )

depmod -b "$PWD"

# Make symlinks to busybox symlinks
for name in `./bin/busybox --list`
do
  [ -e bin/$name -o -e sbin/$name ] && continue
  ln -sT busybox bin/$name
done

ln -sT bin/busybox init

echo "Populate /dev"
install -d dev/pts

for dd in /dev/console /dev/*random /dev/tty /dev/tty? /dev/ttyS0 /dev/zero
do
  cp -a $dd ${dd#/}
done

install -d etc
install -d proc
install -d sys
cat << EOF > etc/fstab
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime,defaults 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime,defaults 0 0
devpts /dev/pts devpts rw,nosuid,noexec,relatime,mode=620,ptmxmode=000 0 0
EOF

cat << EOF > etc/lib
die() {
  echo "$1"
  exit 1
}
EOF

cat << EOF > etc/rcS
#!/bin/sh
set -e -x

. /etc/lib

echo "Mount local file systems"
mount -a

echo "Start mdev"
echo /bin/mdev > /proc/sys/kernel/hotplug
mdev -s

for mod in ata_piix sd_mod cifs hmac md5 md4 arc4 e1000
do
  modprobe \$mod
done

# paranoia wait
sleep 1

echo "Setup network"
IFACE=eth0

ifconfig lo 127.0.0.1 netmask 255.0.0.0 up

if [ "\$IFACE" ]
then
  echo "Setup NIC \$IFACE"
  ifconfig \$IFACE 10.0.2.15 netmask 255.255.255.0 up
  route add default gw 10.0.2.1 metric 1024
  echo "nameserver 10.0.2.1" > /etc/resolv.conf
else
  echo "No NIC"
fi

install -d /mnt/host
mount.cifs -o guest '\\\\10.0.2.4\qemu' /mnt/host

EOF
chmod +x etc/rcS

cat << EOF > etc/rcX
echo "Unmount local file systems"
mount -a -r
EOF
chmod +x etc/rcX

cat << EOF > etc/inittab
::sysinit:/etc/rcS
::askfirst:-/bin/sh
::restart:/init
::ctrlaltdel:/bin/reboot
::shutdown:/etc/rcX
EOF

chmod +x init

echo "Make archive"
find . | cpio -H newc -o | gzip -n9 > ../image.gz
mv ../image.gz "$initfile"
echo "Done with $initfile"
