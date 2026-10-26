# SPDX-FileCopyrightText: 2026 Jasem Mutlaq <mutlaqja@ikarustech.com>
# SPDX-License-Identifier: GPL-2.0-or-later

import glob
import os
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import camera_data as cd  # noqa: E402


def issue_body(**overrides):
    fields = {
        cd.FIELD_CAMERA_ID: "ZWO CCD ASI533MC Pro",
        cd.FIELD_SENSOR: "Color",
        cd.FIELD_GAIN_TYPE: "Adjustable gain (most CMOS cameras)",
        cd.FIELD_GAIN_RANGE: "_No response_",
        cd.FIELD_PIXEL_SIZE: "3.76",
        cd.FIELD_QE: "80%",
        cd.FIELD_READ_NOISE: "```text\n0, 3.8\n100, 1.5\n300, 0.9\n```",
        "Source": "https://example.com/chart",
    }
    fields.update(overrides)
    return "\n\n".join(f"### {key}\n\n{value}" for key, value in fields.items())


class IssueFormTest(unittest.TestCase):
    def test_adjustable_gain_camera(self):
        data = cd.data_from_issue(issue_body())
        self.assertEqual(data["camera_id"], "ZWO CCD ASI533MC Pro")
        self.assertEqual(data["sensor_type"], "COLOR")
        self.assertEqual(data["gain_type"], "NORMAL")
        # The range defaults to the first and last gain of the table.
        self.assertEqual(data["gain_selections"], [0, 300])
        self.assertEqual(data["qe"], 0.8)
        self.assertEqual(data["modes"], [{"number": 0, "name": "Standard",
                                          "table": [(0, 3.8), (100, 1.5), (300, 0.9)]}])

    def test_explicit_gain_range_and_fraction_qe(self):
        data = cd.data_from_issue(issue_body(**{cd.FIELD_GAIN_RANGE: "0, 570",
                                                cd.FIELD_QE: "0.91"}))
        self.assertEqual(data["gain_selections"], [0, 570])
        self.assertEqual(data["qe"], 0.91)

    def test_named_read_modes(self):
        text = "[Photographic]\n0 3.5\n60 1.6\n\n[High Gain Mode]\n0 7\n56 1.2\n"
        data = cd.data_from_issue(issue_body(**{cd.FIELD_READ_NOISE: text}))
        self.assertEqual([(m["number"], m["name"]) for m in data["modes"]],
                         [(0, "Photographic"), (1, "High Gain Mode")])

    def test_dslr_uses_table_gains_as_iso_list(self):
        data = cd.data_from_issue(issue_body(**{
            cd.FIELD_GAIN_TYPE: "ISO (DSLR and mirrorless cameras)",
            cd.FIELD_READ_NOISE: "100, 30\n200, 15\n400, 8"}))
        self.assertEqual(data["gain_type"], "ISO_DISCRETE")
        self.assertEqual(data["gain_selections"], [100, 200, 400])

    def test_fixed_read_noise_camera(self):
        data = cd.data_from_issue(issue_body(**{
            cd.FIELD_GAIN_TYPE: "Fixed, read noise does not depend on gain (CCD cameras)",
            cd.FIELD_READ_NOISE: "9"}))
        self.assertEqual(data["gain_selections"], [0])
        self.assertEqual(data["modes"][0]["table"], [(-1, 9.0), (1, 9.0)])

    def assertRejected(self, body, fragment):
        with self.assertRaises(cd.CameraDataError) as context:
            cd.data_from_issue(body)
        self.assertTrue(any(fragment.lower() in error.lower() for error in context.exception.errors),
                        context.exception.errors)

    def test_rejects_missing_field(self):
        self.assertRejected(issue_body(**{cd.FIELD_PIXEL_SIZE: "_No response_"}),
                            "Pixel size (microns)")

    def test_rejects_unsorted_gains(self):
        self.assertRejected(issue_body(**{cd.FIELD_READ_NOISE: "100, 1.5\n0, 3.8"}),
                            "increasing order")

    def test_rejects_fractional_gain(self):
        self.assertRejected(issue_body(**{cd.FIELD_READ_NOISE: "0, 3.8\n100.5, 1.5"}),
                            "whole number")

    def test_rejects_bad_line(self):
        self.assertRejected(issue_body(**{cd.FIELD_READ_NOISE: "0, 3.8\n100"}),
                            "must contain a gain and a read noise value")

    def test_rejects_unsafe_camera_name(self):
        for name in ("../../etc/passwd", "ZWO_ASI", "QHY 5.0", " "):
            self.assertRejected(issue_body(**{cd.FIELD_CAMERA_ID: name}), "camera name")

    def test_rejects_out_of_range_qe(self):
        self.assertRejected(issue_body(**{cd.FIELD_QE: "180"}), "Quantum efficiency")


class FileTest(unittest.TestCase):
    def test_generated_file_round_trips_and_validates(self):
        data = cd.data_from_issue(issue_body())
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, cd.camera_id_to_file_name(data["camera_id"]))
            with open(path, "w", encoding="utf-8") as f:
                f.write(cd.to_xml(data))
            self.assertEqual(cd.validate_file(path), [])
            self.assertEqual(cd.parse_xml(path), data)

    def test_reads_modes_nested_in_one_element(self):
        xml = textwrap.dedent("""\
            <ExposureCalculatorCameraData>
                <CameraDataClassVersion>1</CameraDataClassVersion>
                <CameraId>Test Cam</CameraId>
                <SensorType>MONOCHROME</SensorType>
                <GainSelectionType>NORMAL</GainSelectionType>
                <CameraGainSelections><GainSelection>0</GainSelection><GainSelection>10</GainSelection></CameraGainSelections>
                <CameraGainReadMode>
                    <GainReadModeNumber>0</GainReadModeNumber><GainReadModeName>A</GainReadModeName>
                    <CameraGainReadNoise>
                        <GainReadNoiseValue><Gain>0</Gain><ReadNoise>3</ReadNoise></GainReadNoiseValue>
                        <GainReadNoiseValue><Gain>10</Gain><ReadNoise>2</ReadNoise></GainReadNoiseValue>
                    </CameraGainReadNoise>
                    <GainReadModeNumber>1</GainReadModeNumber><GainReadModeName>B</GainReadModeName>
                    <CameraGainReadNoise>
                        <GainReadNoiseValue><Gain>0</Gain><ReadNoise>5</ReadNoise></GainReadNoiseValue>
                        <GainReadNoiseValue><Gain>10</Gain><ReadNoise>4</ReadNoise></GainReadNoiseValue>
                    </CameraGainReadNoise>
                </CameraGainReadMode>
                <CameraPixelSize>3.76</CameraPixelSize>
                <CameraQuantumEfficiency>0.8</CameraQuantumEfficiency>
            </ExposureCalculatorCameraData>
            """)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "Test_Cam.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(xml)
            self.assertEqual(cd.validate_file(path), [])
            self.assertEqual([m["name"] for m in cd.parse_xml(path)["modes"]], ["A", "B"])

    def test_rejects_misnumbered_modes(self):
        data = cd.data_from_issue(issue_body())
        data["modes"][0]["number"] = 1
        self.assertTrue(any("numbered 0, 1, 2" in e for e in cd.check_data(data)))

    def test_rejects_unknown_element(self):
        data = cd.data_from_issue(issue_body())
        text = cd.to_xml(data).replace("<CameraPixelSize>", "<CameraPixelSise>1</CameraPixelSise>"
                                       "<CameraPixelSize>")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ZWO_CCD_ASI533MC_Pro.xml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertTrue(any("CameraPixelSise" in e for e in cd.validate_file(path)))

    def test_all_repository_files_are_valid(self):
        files = sorted(glob.glob(os.path.join(HERE, "..", "cameras", "*.xml")))
        self.assertTrue(files)
        for path in files:
            with self.subTest(file=os.path.basename(path)):
                self.assertEqual(cd.validate_file(path), [])


if __name__ == "__main__":
    unittest.main()
