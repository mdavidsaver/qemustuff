#!/bin/sh
set -e -x

# cf. https://developer.microsoft.com/en-us/windows/downloads/virtual-machines
#     and ./windows-guest.txt

# prep.
#   sudo apt-get install ovmf swtpm qemu-system-x86 spicy

# Sets up TPM and UEFI boot.
# Spice graphics and qemu-guest-agent connections
# User mode networking
# also virtio RNG and memory balloon

RAM=6G
CORES=4
USERNET=

usage() {
    echo "$0 [-m RAM] [-j CPU] [-N netopt] <vm.img> [QEMU args...]"
    [ "$1" ] && printf "\nERROR: %1\n" "$1"
    exit 1
}

while getopts m:j:N: arg
do
    case "$arg" in
    m) RAM="$arg";;
    j) CORES="$arg";;
    N) USERNET="$USERNET,$arg";;
    \?) usage;;
    esac
done
shift `expr $OPTIND - 1`

# expect something like Win11.img
IMG="$1"
shift

[ "$IMG" -a -f "$IMG" ] || usage "Not a file: $IMG"

# swtpm state directory
TPM="${IMG%.img}.tpm"
# OVMF variables file
OVMF="${IMG%.img}.ovmf"
# QEMU guest agent socket
GA="${IMG%.img}.ga.sock"

[ -d "$TPM" ] || mkdir "$TPM"

[ -f "$OVMF" ] || cp /usr/share/OVMF/OVMF_VARS.fd "$OVMF"

# when run in foreground, swtpm will exit automatically after a
# successfull connect and disconnect.  So we only need to cleanup
# if we crash before starting qemu
swtpm socket --tpm2 \
 --ctrl type=unixio,path="$TPM/sock" \
 --tpmstate dir="$TPM" \
 --log file="$TPM/log",level=20 \
 &

TPMPID="$!"
# validate the PID
kill -0 "$TPMPID"
# setup automatic cleanup
trap 'kill -0 "$TPMPID" && kill -TERM "$TPMPID"; rm -f "$GA"' TERM QUIT INT STOP EXIT

SPICE=5990

echo "spice port $SPICE"

spicy -p "$SPICE" &

qemu-system-x86_64 -enable-kvm \
 -machine q35 \
 -cpu host,hv_vpindex,hv_runtime,hv_synic,hv_stimer,hv_reset,hv_time,hv_relaxed \
 -smp "$CORES" \
 -m "$RAM" \
 -usb -usbdevice tablet \
 -device intel-iommu \
 -bios /usr/share/OVMF/OVMF_CODE.fd \
 -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
 -drive if=pflash,format=raw,file="$OVMF" \
 -drive if=ide,file="$IMG" \
 -chardev socket,id=tpmsock,path="$TPM"/sock \
 -tpmdev emulator,id=tpm,chardev=tpmsock \
 -device tpm-tis,tpmdev=tpm \
 -device virtio-balloon \
 -device virtio-rng-pci,rng=rng0 \
 -object rng-random,id=rng0,filename=/dev/urandom \
 -net nic,model=e1000 \
 -net user,smb="$HOME""$USERNET" \
 -display none \
 -vga qxl \
 -device virtio-serial-pci \
 -spice addr=127.0.0.1,port="$SPICE",ipv4=on,disable-ticketing=on \
 -device virtserialport,chardev=spicechannel0,name=com.redhat.spice.0 \
 -chardev spicevmc,id=spicechannel0,name=vdagent \
 -chardev socket,path="$GA",server=on,wait=off,id=agent \
 -device virtserialport,chardev=agent,name=org.qemu.guest_agent.0 \
 "$@"
