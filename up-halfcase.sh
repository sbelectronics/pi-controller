rsync -avz --exclude "__history" --exclude "*~" --exclude "*.gif" --exclude "*.JPG" -e ssh . ../nixiecalc/ioexpand.py ../nixiecalc/keyboard.py ../pi-vfd/vfd.py ../pi-stereo/motorpot.py ../pi-stereo/motor.py ../pi-stereo/ads1015.py pi@198.0.0.242:/home/pi/pi-controller
#scp ../nixiecalc/ioexpand.py ../nixiecalc/keyboard.py ../pi-vfd/vfd.py pi@198.0.0.242:/home/pi/pi-controller
