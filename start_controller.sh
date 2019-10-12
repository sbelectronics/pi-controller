#! /bin/bash
echo "start_controller.sh started" > /tmp/controller.script
printf "%s" "waiting for ServerXY ..."
while ! ping -c 1 -n -w 1 198.0.0.108 &> /dev/null
do
    printf "%c" "."
done
cd /home/pi
nohup python controller.py -m > /tmp/controller.out 2> /tmp/controller.err &
echo "start_Ccontroller.sh exiting" >> /tmp/controller.script
