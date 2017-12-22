#!/bin/bash

CFILE=/run/media/pieter/ext-drive/gr-lora-paper/test-suites/snr_short_rn2483_usrphg/usrphg-868.1-sf7-cr4-bw125-crc-0.sigmf-data

if [ "$1" == "noise" ]; then
    ./pdr_comparison.py --clean --noise 0 $CFILE
    for i in $(seq 0.010 0.010 0.320)
    #for i in $(seq 0.1 0.1 2.2)
    do
        ./pdr_comparison.py --noise $i $CFILE
    done
elif [ "$1" == "offset" ]; then
    ./pdr_comparison.py --clean --offset 0 $CFILE
    for i in $(seq 25000 25000 300000)
    do
        ./pdr_comparison.py --offset $i $CFILE
    done
else
    echo "Argument must be 'noise' or 'offset'"
fi
