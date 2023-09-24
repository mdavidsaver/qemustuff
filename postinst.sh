
echo "postinst.sh was here" > /target/HEREIAM

#echo "\\\\10.0.2.4\\qemu /mnt/host cifs _netdev,guest,uid=1000,gid=1000,defaults 0 0" >> /target/etc/fstab
echo "home /mnt/host 9p trans=virtio,defaults 0 0" >> /target/etc/fstab

mkdir /target/mnt/host
