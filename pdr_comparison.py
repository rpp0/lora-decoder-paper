#!/usr/bin/env python2

import os
import argparse
import signal
import socket
import osmosdr
import lora
import binascii
import numpy as np
from time import sleep
from threading import Thread
from gnuradio import gr, gr_unittest, blocks, filter, uhd, analog
from gnuradio.filter import firdes
from loranode import RN2483Controller

def signal_handler(signal, frame):
    exit(0)

class Transmitter(Thread):
    def __init__(self, path, noise=0, offset=0, sample_rate=1000000):
        Thread.__init__(self)
        self.setDaemon(True)

        # Build flowgraph
        self.sample_rate = sample_rate
        self.tb = gr.top_block()
        self.noise_source = analog.noise_source_c(analog.GR_GAUSSIAN, noise, ord(os.urandom(1)))
        self.add = blocks.add_cc()
        self.file_source = blocks.file_source(gr.sizeof_gr_complex, path, False)
        self.throttle = blocks.throttle(gr.sizeof_gr_complex, self.sample_rate, True)
        self.freq_xlating_fir_filter = filter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1, self.sample_rate, 85000, 10000, firdes.WIN_HAMMING, 6.67)), 100000, self.sample_rate)
        self.usrp_sink = uhd.usrp_sink(
            ",".join(("", "")),
            uhd.stream_args(
                cpu_format="fc32",
                    channels=range(1),
            ),
        )
        self.usrp_sink.set_samp_rate(self.sample_rate)
        self.usrp_sink.set_center_freq(868.1e6+offset, 0)
        self.usrp_sink.set_gain(70, 0)
        self.usrp_sink.set_antenna('TX/RX', 0)

        # Make connections
        self.tb.connect((self.file_source, 0), (self.throttle, 0))
        self.tb.connect((self.throttle, 0), (self.add, 0))
        self.tb.connect((self.noise_source, 0), (self.add, 1))
        self.tb.connect((self.add, 0), (self.freq_xlating_fir_filter, 0))
        self.tb.connect((self.freq_xlating_fir_filter, 0), (self.usrp_sink, 0))

    def run(self):
        self.tb.start()
        self.tb.wait()

class ReceiverHW(Thread):
    def __init__(self, num_messages):
        Thread.__init__(self)
        self.setDaemon(True)
        self.num_messages = num_messages
        self.lc = RN2483Controller("/dev/lora")
        self.lc.set_sf(7)
        self.name = "receiver_hw"
        self.data = {
            'payloads': [],
            'snrs': []
        }

    def run(self):
        payloads = []
        snrs = []

        for i in range(0, self.num_messages):
            payloads.append(str(self.lc.recv_p2p()).lower())
            snrs.append(float(self.lc.eval("radio get snr")))
            self.data = {'payloads': payloads, 'snrs': snrs}  # Update data


class ReceiverSDR(Thread):
    def __init__(self, num_messages, sample_rate=1000000, freq_offset=10000, sf=7, name="rtl-sdr"):
        Thread.__init__(self)
        self.setDaemon(True)
        self.num_messages = num_messages
        self.sample_rate = sample_rate
        self.freq_offset = freq_offset
        self.frequency = 868e6
        self.name = name

        self.data = {
            'payloads': [],
            'snrs': []
        }

        # Variables
        self.host = "127.0.0.1"
        self.port = 40868

        # Setup socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.settimeout(1)

        # Build flowgraph
        self.tb = gr.top_block()
        self.rtlsdr_source = osmosdr.source( args="numchan=" + str(1) + " " + '' )
        self.rtlsdr_source.set_sample_rate(self.sample_rate)
        self.rtlsdr_source.set_center_freq(self.frequency, 0)
        self.rtlsdr_source.set_freq_corr(0, 0)
        self.rtlsdr_source.set_dc_offset_mode(0, 0)
        self.rtlsdr_source.set_iq_balance_mode(0, 0)
        self.rtlsdr_source.set_gain_mode(False, 0)
        self.rtlsdr_source.set_gain(10, 0)
        self.rtlsdr_source.set_if_gain(20, 0)
        self.rtlsdr_source.set_bb_gain(20, 0)
        self.rtlsdr_source.set_antenna('', 0)
        self.rtlsdr_source.set_bandwidth(0, 0)
        self.freq_xlating_fir_filter = filter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1, self.sample_rate, 500000, 100000, firdes.WIN_HAMMING, 6.67)), self.freq_offset, self.sample_rate)
        self.lora_receiver = lora.lora_receiver(self.sample_rate, self.frequency, [868100000], sf, 1000000, False, 4, True)
        self.message_socket_sink = lora.message_socket_sink("127.0.0.1", 40868, 0)

        # Make connections
        self.tb.connect((self.rtlsdr_source, 0), (self.freq_xlating_fir_filter, 0))
        self.tb.connect((self.freq_xlating_fir_filter, 0), (self.lora_receiver, 0))
        self.tb.msg_connect((self.lora_receiver, 'frames'), (self.message_socket_sink, 'in'))

    def run(self):
        self.tb.start()

        self.get_data(self.num_messages)

        print("Stopping receiving")

        self.tb.stop()

    def __del__(self):
        self.server.close()

    def get_data(self, number):
        """
        Returns array of <number> hexadecimal LoRa payload datagrams received on a socket.
        """
        payloads = []
        snrs = []
        received = ''

        for i in range(number):
            try:
                received = self.server.recvfrom(65535)[0]
                if received:
                    loratap = received[0:15]
                    loraphy = received[15:18]
                    hasmac = True if ord(loraphy[1]) & 0x10 else False
                    if hasmac:
                        payload = received[18:-2]
                    else:
                        payload = received[18:]
                    snr = ord(loratap[13])

                    payloads.append(binascii.hexlify(payload))
                    snrs.append(snr)
                    self.data['payloads'] = payloads
                    self.data['snrs'] = snrs
            except Exception as e:
                print(e)
                pass

def calculate_pdr(receiver, expected_message, expected_number, output_path, offset):
    payloads = receiver.data['payloads']
    snr = np.nanmean(receiver.data['snrs'])
    if np.isnan(snr):
        snr = 0

    correct = 0
    for i in range(0, expected_number):
        try:
            if payloads[i] == expected_message:
                correct += 1
        except IndexError:
            pass
    pdr = float(correct) / float(expected_number)
    per = 1.0 - pdr

    with open(os.path.join(output_path, receiver.name + "-snr.gnuplot"), "a") as f:
        f.write("%f %f\n" % (snr, per))

    with open(os.path.join(output_path, receiver.name + "-offset.gnuplot"), "a") as f:
        f.write("%f %f\n" % (offset, per))

    return snr, per

def delete_existing_results(output_path):
    for filename in os.listdir(output_path):
        if filename.endswith(".gnuplot"):
            filepath = os.path.join(output_path, filename)
            os.remove(filepath)
            print("Removing %s" % filepath)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Tool to compare SDR LoRa decoder with real hardware decoder.")
    parser.add_argument('cfile', type=str, default=None, help='Path to cfile to transmit')
    parser.add_argument('--noise', type=float, default=0, help='Artificial noise to add')
    parser.add_argument('--offset', type=int, default=0, help='Artificial frequency offset to add')
    parser.add_argument('--clean', default=False, action="store_true", help='Delete files in output path')
    signal.signal(signal.SIGINT, signal_handler)
    args = parser.parse_args()

    output_path = "./pdr_comparison/"
    num_messages = 100
    payload = "0123456789abcdef"

    # Create output dir if it doesnt exist yet
    if not os.path.exists(output_path):
        os.makedirs(output_path)

    if args.clean:
        print("Cleaning")
        delete_existing_results(output_path)

    print("Noise: %f" % args.noise)
    print("Offset: %d" % args.offset)

    transmitter = Transmitter(args.cfile, args.noise, offset=args.offset)
    receiver_sdr = ReceiverSDR(num_messages, sample_rate=1000000, freq_offset=-30000, sf=7, name="rtl-sdr")
    receiver_hw = ReceiverHW(num_messages)
    receiver_hw.start()
    receiver_sdr.start()
    transmitter.start()
    transmitter.join()

    # Don't wait for receivers, but give them 1 more second to process everything
    sleep(1)

    print("SDR: %s" % str(calculate_pdr(receiver_sdr, payload, num_messages, output_path, args.offset)))
    print("HW : %s" % str(calculate_pdr(receiver_hw, payload, num_messages, output_path, args.offset)))
