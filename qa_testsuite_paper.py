#!/usr/bin/env python2
import lora
import socket
import pmt
import time
import collections
import datetime
import os.path
import os
import json
import binascii
import signal
import argparse
import numpy as np
import gc

from gnuradio import gr, gr_unittest, blocks, filter, analog
from gnuradio.filter import firdes
from sigmf.sigmffile import SigMFFile
from lora.loraconfig import LoRaConfig

Test = collections.namedtuple('Test', ['payload', 'times'])
TestResult = collections.namedtuple('TestResult', ['data', 'lora_config', 'test'])

def signal_handler(signal, frame):
        exit(0)

def trunc(target, max_len=30):
    result = ""
    if len(target) > max_len:
        result += target[0:max_len/2-1]
        result += ".."
        result += target[-max_len/2+1:]
    else:
        result = target
    assert(len(result) <= max_len)
    return result

class TestSummary():
    def __init__(self, suite, pause=False):
        self.pause = pause
        self.suite = suite
        self._summary = []
        self._summary_text = "-------- Test suite '{:s}' results on {:s} ---------\n".format(suite, str(datetime.datetime.utcnow()))
        self._summary_markdown = "# Test suite: '{:s}'\n\n*Results on {:s}*\n".format(suite, str(datetime.datetime.utcnow()))
        self._num_total_correct_payloads = 0
        self._num_total_payloads = 0
        self._num_tests = 0
        self._last_config = None
        self._mean_snrs = []

    def get_total_mean_snr(self):
        return np.mean(self._mean_snrs)

    def get_total_per(self):
        return (1.0 - float(self._num_total_correct_payloads) / float(self._num_total_payloads))

    def add(self, test_result, print_intermediate=False):
        if type(test_result) == TestResult:
            self._summary.append(test_result)
            self._evaluate_result(test_result, print_intermediate)
        else:
            raise Exception("Test result must be of type TestResult")

    def export_summary(self, path, print_output=True, write_output=True):
        self._summary_text += "\nRan a total of {:n} tests, together containing {:n} payloads.\n".format(
            self._num_tests,
            self._num_total_payloads
        )
        self._summary_text += "====== Total payloads passed: {:>5n} out of {:<5n}  ({:.2%}) ======\n".format(
            self._num_total_correct_payloads,
            self._num_total_payloads,
            float(self._num_total_correct_payloads) / self._num_total_payloads
        )

        self._summary_markdown += "\n### Summary for suite '{:s}'\n\n".format(self.suite)
        self._summary_markdown += "Total payloads passed: {:n} out of {:n} ({:.2%})\n\n".format(
            self._num_total_correct_payloads,
            self._num_total_payloads,
            float(self._num_total_correct_payloads) / self._num_total_payloads
        )

        if print_output:
            print(self._summary_text)

        if not os.path.exists(path):
            os.makedirs(path)
        with open(os.path.join(path, self.suite + '.md'), 'w') as f:
            f.write(self._summary_markdown)
        with open(os.path.join(path, self.suite + '-snr.gnuplot'), 'a') as f:
            f.write(str(self.get_total_mean_snr()) + " " + str(self.get_total_per()) + "\n")

    def _evaluate_result(self, test_result, print_intermediate):
        """
        Given a test result, evaluate it and generate text / markdown for the report.
        """
        self._num_tests += 1
        evaluation_text = ""
        evaluation_markdown = ""

        # Shorter names
        data = test_result.data
        payloads = data['payloads']
        snrs = data['snrs']
        mean_snr = np.nanmean(snrs)
        if np.isnan(mean_snr):
            mean_snr = 0
        self._mean_snrs.append(mean_snr)
        lora_config = test_result.lora_config
        test = test_result.test
        expected_data = [test.payload] * test.times

        # Don't reprint configuration if it is the same as before
        if(self._last_config != vars(lora_config)):
            evaluation_text += "{:s}:\n".format(lora_config.string_repr())
            evaluation_markdown += "\n### {:s}\n\nTransmitted payload | :heavy_check_mark: | :hash: | :heavy_division_sign:\n--- | --- | --- | ---\n".format(lora_config.string_repr())
            self._last_config = vars(lora_config)

        # Determine number of correct payloads
        num_payloads = 0
        num_correct_payloads = 0
        for i in range(0, test.times):
            num_payloads += 1
            self._num_total_payloads += 1

            try:
                decoded = payloads[i]
            except IndexError:
                decoded = "?"
            try:
                expected = expected_data[i]
            except IndexError:
                expected = "?"

            if decoded == expected:
                num_correct_payloads += 1
                self._num_total_correct_payloads += 1
            else:
                if self.pause:
                    _ = raw_input("Expected %s but got %s for %s. Press enter to continue..." % (expected, decoded, lora_config.string_repr()))

        # Append to text report
        evaluation_text += "\tTest {:>3n}: {:<30s} * {:<3n} :: passed {:>3n} out of {:<3n} ({:.2%}) | SNR: {:>3.1f} dB\n".format(
            self._num_tests,
            trunc(test.payload),
            test.times,
            num_correct_payloads,
            num_payloads,
            float(num_correct_payloads)/num_payloads,
            mean_snr
        )
        self._summary_text += evaluation_text

        # Append to markdown report
        evaluation_markdown += "`{:<30s}` | {:>3n} | {:>3n} | {:>.2%}\n".format(
            trunc(test.payload),
            num_correct_payloads,
            num_payloads,
            float(num_correct_payloads)/num_payloads
        )
        self._summary_markdown += evaluation_markdown

        if(print_intermediate):
            print(evaluation_text)


class qa_testsuite():
    def __init__(self, path=None):
        """
        Determine installed test suites and setup socket server for receiving payloads decoded by gr-lora.
        """
        # Variables
        self.host = "127.0.0.1"
        self.port = 40868

        # Setup socket
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.settimeout(1)

        # Determine test suites directory if needed
        self.test_suites_directory = os.path.abspath(path)
        self.reports_directory = os.path.abspath(path + '/../test-results-paper')


        # List test suites
        self.test_suites = []
        if os.path.exists(self.test_suites_directory):
            self.test_suites = [x for x in os.listdir(self.test_suites_directory) if os.path.isdir(os.path.join(self.test_suites_directory, x))]
        else:
            print("No test suites found! Skipping...")

    def __del__(self):
        self.server.close()

    def get_data(self, number):
        """
        Returns array of <number> hexadecimal LoRa payload datagrams received on a socket.
        """
        data = {}
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
            except Exception as e:
                print(e)
                pass

        data['payloads'] = payloads
        data['snrs'] = snrs

        return data

    def run(self, suites_to_run, pause=False, write_output=True, noise_amp=0):
        for test_suite in self.test_suites:
            # Skip test suites that we don't want to run
            if suites_to_run != [] and (not test_suite in suites_to_run):
                continue

            print("[+] Testing suite: '%s'" % test_suite)
            summary = TestSummary(suite=test_suite, pause=pause)

            # Get all metadata files associated with the suite
            get_mtime = lambda f: os.stat(os.path.join(self.test_suites_directory, test_suite, f)).st_mtime
            metadata_files = [os.path.join(self.test_suites_directory, test_suite, x) for x in sorted(os.listdir(os.path.join(self.test_suites_directory, test_suite)), key=get_mtime) if x.endswith('.sigmf-meta')]

            # Parse metadata files
            for metadata_file in metadata_files:
                print("[+] %s" % metadata_file)
                data_file = os.path.splitext(metadata_file)[0] + '.sigmf-data'
                # Load sigmf data TODO abstract
                f = open(metadata_file, 'r')
                sigmf = SigMFFile(metadata=f.read())
                if not sigmf.validate():
                    raise Exception("Invalid SigMF format")
                global_meta = sigmf.get_global_info()
                capture_meta = sigmf.get_capture_info(0)
                f.close()

                # Initialize test parameters
                sample_rate = global_meta["core:sample_rate"]

                # Get LoRa configuration
                capture_freq = capture_meta["core:frequency"]
                if "lora:frequency_offset" in capture_meta:
                    frequency_offset = capture_meta["lora:frequency_offset"]
                else:
                    frequency_offset = 0
                transmit_freq = capture_meta["lora:frequency"]
                sf = capture_meta["lora:sf"]
                cr = capture_meta["lora:cr"]
                bw = capture_meta["lora:bw"]
                prlen = capture_meta["lora:prlen"]
                crc = capture_meta["lora:crc"]
                implicit = capture_meta["lora:implicit"]
                lora_config = LoRaConfig(transmit_freq, sf, cr, bw, prlen, crc, implicit)

                # Get test case configuration
                payload = capture_meta["test:expected"]
                times = capture_meta["test:times"]
                test = Test(payload, times)

                # Build flowgraph
                tb = gr.top_block()
                noise_source = analog.noise_source_c(analog.GR_GAUSSIAN, noise_amp, ord(os.urandom(1)))
                add = blocks.add_cc()
                file_source = blocks.file_source(gr.sizeof_gr_complex, data_file, False)
                lora_receiver = lora.lora_receiver(sample_rate, capture_freq, [868100000], sf, 1000000, False, 4, True)
                throttle = blocks.throttle(gr.sizeof_gr_complex, sample_rate, True)
                message_socket_sink = lora.message_socket_sink("127.0.0.1", 40868, 0)
                freq_xlating_fir_filter = filter.freq_xlating_fir_filter_ccc(1, (firdes.low_pass(1, sample_rate, 200000, 100000, firdes.WIN_HAMMING, 6.67)), frequency_offset, sample_rate)

                # Make connections
                tb.connect((file_source, 0), (throttle, 0))
                tb.connect((throttle, 0), (add, 0))
                tb.connect((noise_source, 0), (add, 1))
                tb.connect((add, 0), (freq_xlating_fir_filter, 0))
                tb.connect((freq_xlating_fir_filter, 0), (lora_receiver, 0))
                tb.msg_connect((lora_receiver, 'frames'), (message_socket_sink, 'in'))
                tb.start()
                tb.wait()

                data = self.get_data(times)  # Output from the flowgraph
                summary.add(TestResult(data=data, lora_config=lora_config, test=test), print_intermediate=True)
            # Finally, export the result for the suite
            summary.export_summary(path=self.reports_directory, write_output=write_output)
            del summary
            del data
            del tb
            gc.collect()

    def remove_existing_snr_reports(self, noconfirm):
        if not noconfirm:
            confirm = raw_input("Really remove existing SNR reports? (y/N) ")
        else:
            confirm = "y"
        if confirm.lower() == "y":
            for test_suite in self.test_suites:
                file_path = os.path.join(self.reports_directory, test_suite + '-snr.gnuplot')
                if os.path.exists(file_path):
                    print("Removing %s" % file_path)
                    os.remove(file_path)

if __name__ == '__main__':
    """
    Tool to evaluate decoding test suites, modified for the paper
    """
    # Parse args
    parser = argparse.ArgumentParser(description="Tool to evaluate decoding test suites for gr-lora.")
    parser.add_argument('path', type=str, default=None, help='Path of the test suites')
    parser.add_argument('suites', type=str, nargs="*", help='Names of the test suites to execute.')
    parser.add_argument('--pause', action="store_true", default=False, help='Pause upon encountering an error.')
    parser.add_argument('--write', action="store_true", default=False, help='Write output to files.')
    parser.add_argument('--clean', action="store_true", default=False, help='Clean SNR files.')
    parser.add_argument('--noise', type=float, default=0, help='Noise')
    args = parser.parse_args()

    # Make sure CTRL+C exits the whole test suite instead of only the current GNU Radio top block
    signal.signal(signal.SIGINT, signal_handler)

    print("Using noise %f" % args.noise)
    suite = qa_testsuite(args.path)
    if args.clean:
        suite.remove_existing_snr_reports(args.clean)
    suite.run(suites_to_run=args.suites, pause=args.pause, write_output=args.write, noise_amp=args.noise)
