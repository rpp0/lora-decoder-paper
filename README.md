# A Multi-Channel Software Decoder for the LoRa Modulation Scheme

This repository contains the datasets and code for reproducing the results presented within the paper "A Multi-Channel Software Decoder for the LoRa Modulation Scheme".

- Paper download: TBA
- Datasets download: [https://research.edm.uhasselt.be/probyns/lora/amcsdlms-datasets.zip](https://research.edm.uhasselt.be/probyns/lora/amcsdlms-datasets.zip)
- Decoder download (`gr-lora`): [https://github.com/rpp0/gr-lora](https://github.com/rpp0/gr-lora)

Before proceeding, make sure `gr-lora` is correctly installed.

## Compatibility experiment results
1. Acquire the three different types of transmitters (RN2483, SX1272, RFM96).
2. Generate the traces by sending 100 messages containing `0123456789abcdef` for each possible configuration and each transmitter, and capturing with the USRP at 1 Msps. The total recorded size of these traces is 31.6 GB, and is therefore by default not included in the datasets download. It is recommended to generate the datasets yourself, but the compatibility datasets are available on request.
3. Run the `qa_testsuite_paper.py` script with the path argument set to the root directory containing the folder with traces and the suites argument to the trace folder name. Example: `./qa_testsuite_paper.py ~/mytraces/ compat_experiment_traces`. A report will be generated in `~/mytraces/../test-results` containing the PDR for each configuration. These can be used to create Table 1.

## Accuracy experiment results
### Effect of Gaussian noise
1. Edit the script `snr_experiment_dedicated.sh` DIRECTORY variable to point to the datasets folder.
2. Run the script. Results will be stored in `$DIRECTORY/../test-results-paper.`
3. The `.gnuplot` files in the results directory contain the x and y values of Figure 8.

### Comparison with real hardware
1. Setup the RN2483 hardware, USRP (transmitter), and RTL-SDR (receiver) as described in the paper. The RN2483 hardware should have a serial interface available at `/dev/lora` (e.g. symlinked to `/dev/ttyUSB0`).
2. Download and install [python-loranode](https://github.com/rpp0/python-loranode) from Github. This is required to send commands to the hardware.
3. Edit the script `pdr_comparison_experiment.sh` CFILE variable to point to the `snr_short_rn2483_usrphg/usrphg-868.1-sf7-cr4-bw125-crc-0.sigmf-data` file.
4. Run the script. The results will be stored in `./pdr_comparison/`. The `*-snr.gnuplot` and `*-offset.gnuplot` files contain x and y values for Figure 9a and Figure 9b respectively.

## Citing this work

TBA
