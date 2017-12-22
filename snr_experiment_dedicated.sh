#!/bin/bash

DIRECTORY=/run/media/pieter/ext-drive/gr-lora-paper/test-suites

# Clean the previous SNR files
./qa_testsuite_paper.py --clean --noise 0 $DIRECTORY snr_short_rn2483_usrp snr_short_rn2483_hackrf snr_short_rn2483_rtl-sdr

# Generate SNR files
# We need different noise values because the 'default' noise floor of the devices
# differs. This does not affect the SNR calculation itself.
for i in $(seq 0.0002 0.0002 0.01)
do
    ./qa_testsuite_paper.py --noise $i $DIRECTORY snr_short_rn2483_usrp
done

for i in $(seq 0.010 0.010 0.300)
do
    ./qa_testsuite_paper.py --noise $i $DIRECTORY snr_short_rn2483_rtl-sdr
done

for i in $(seq 0.03 0.03 0.94)
do
    ./qa_testsuite_paper.py --noise $i $DIRECTORY snr_short_rn2483_hackrf
done
