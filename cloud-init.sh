#!/bin/sh
set -e -x

# Pack up cloud-init/ into an ISO image file
#
# ./cloud-init.sh out.iso

# https://docs.cloud-init.io/en/latest/tutorial/qemu.html
# https://docs.cloud-init.io/en/latest/reference/datasources/nocloud.html

# sudo cloud-init schema --system --annotate
# cloud-init schema -c test.yml --annotate


#    https://rockylinux.org/download
#    https://fedoraproject.org/cloud/
#    https://cloud.debian.org/images/cloud/
#    https://cloud-images.ubuntu.com/


die() {
    echo "$0 <out.iso> [src/]"
    echo "$1" >&2
    exit 1
}

OUT="$1"
SRC="${2:-.}"

for req in user-data meta-data vendor-data
do
    [ -f "$SRC/$req" ] || die "Missing required: $SRC/$req"
done

TOUT="$(mktemp)"
trap 'rm -f "$TOUT"' QUIT INT TERM

# https://docs.cloud-init.io/en/24.3/howto/run_cloud_init_locally.html
(cd "$SRC" \
 && genisoimage -o "$TOUT" -V cidata -J -R * \
)

mv "$TOUT" "$OUT"
