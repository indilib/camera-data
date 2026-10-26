#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Jasem Mutlaq <mutlaqja@ikarustech.com>
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate camera data files and generate them from GitHub issue forms.

The files are read by the KStars Exposure Calculator. KStars does not validate
them, so a malformed file produces wrong exposure times or crashes the
calculator. Every rule enforced here protects against such a failure.

Usage:
    camera_data.py validate [FILE ...]          (default: cameras/*.xml)
    camera_data.py from-issue --body-file BODY --out-dir cameras
    camera_data.py normalize [FILE ...]         (rewrite in canonical form)
"""

import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

SENSOR_TYPES = ("MONOCHROME", "COLOR")
GAIN_TYPES = ("NORMAL", "ISO_DISCRETE", "FIXED")

# The camera name becomes the file name, so keep it to characters that are
# safe in file names and URLs on every platform. KStars turns "_" back into
# spaces and stops the name at the first ".", so neither may appear.
CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ()+\-]*[A-Za-z0-9)]$")

MAX_PIXEL_SIZE = 50.0

ROOT_ELEMENTS = {
    "CameraDataClassVersion", "CameraId", "SensorType", "GainSelectionType",
    "CameraGainSelections", "CameraGainReadMode", "CameraPixelSize",
    "CameraQuantumEfficiency",
}
READ_MODE_ELEMENTS = {"GainReadModeNumber", "GainReadModeName", "CameraGainReadNoise"}


class CameraDataError(Exception):
    """Raised when camera data cannot be parsed or is invalid."""

    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


def camera_id_to_file_name(camera_id):
    return camera_id.replace(" ", "_") + ".xml"


def file_name_to_camera_id(file_name):
    return os.path.basename(file_name)[:-len(".xml")].replace("_", " ")


def check_camera_id(camera_id):
    if not camera_id:
        return ["The camera name is empty."]
    if not CAMERA_ID_RE.match(camera_id):
        return [f"The camera name '{camera_id}' may only contain letters, digits, spaces and the "
                "characters ( ) + - and must start and end with a letter or digit."]
    if "  " in camera_id:
        return [f"The camera name '{camera_id}' contains two spaces in a row."]
    return []


def _parse_int(text, what, errors):
    try:
        return int(text.strip())
    except (AttributeError, ValueError):
        errors.append(f"{what} must be a whole number, got '{text}'.")
        return None


def _parse_float(text, what, errors):
    try:
        return float(text.strip())
    except (AttributeError, ValueError):
        errors.append(f"{what} must be a number, got '{text}'.")
        return None


def check_data(data):
    """Return a list of problems with a camera data dictionary."""
    errors = check_camera_id(data["camera_id"])

    if data["sensor_type"] not in SENSOR_TYPES:
        errors.append(f"SensorType must be one of {', '.join(SENSOR_TYPES)}.")
    gain_type = data["gain_type"]
    if gain_type not in GAIN_TYPES:
        errors.append(f"GainSelectionType must be one of {', '.join(GAIN_TYPES)}.")

    selections = data["gain_selections"]
    if gain_type == "NORMAL":
        if len(selections) != 2 or selections[0] >= selections[1]:
            errors.append("A camera with adjustable gain needs exactly two gain selections: "
                          "the minimum and the maximum gain, minimum first.")
    elif gain_type == "ISO_DISCRETE":
        if not selections or selections != sorted(set(selections)) or selections[0] <= 0:
            errors.append("A DSLR needs a list of positive ISO values in increasing order "
                          "without duplicates.")
    elif gain_type == "FIXED":
        if selections != [0]:
            errors.append("A camera with fixed read noise needs a single gain selection of 0.")

    modes = data["modes"]
    if not modes:
        errors.append("At least one read-noise table is required.")
    for index, mode in enumerate(modes):
        label = f"Read mode {index} ('{mode['name']}')"
        # KStars uses the mode number as a position in its list of modes.
        if mode["number"] != index:
            errors.append(f"{label}: read modes must be numbered 0, 1, 2... in order, "
                          f"but this one is numbered {mode['number']}.")
        if not mode["name"].strip():
            errors.append(f"Read mode {index} has no name.")
        table = mode["table"]
        minimum_rows = 1 if gain_type == "FIXED" else 2
        if len(table) < minimum_rows:
            errors.append(f"{label}: needs at least {minimum_rows} gain / read noise rows.")
        gains = [gain for gain, _ in table]
        # Read noise between two listed gains is interpolated, which needs
        # the gains in increasing order.
        if gains != sorted(set(gains)):
            errors.append(f"{label}: gains must be in increasing order without duplicates.")
        for gain, read_noise in table:
            if read_noise <= 0:
                errors.append(f"{label}: read noise at gain {gain} must be greater than 0.")

    pixel_size = data["pixel_size"]
    if pixel_size is None or not 0 < pixel_size <= MAX_PIXEL_SIZE:
        errors.append(f"Pixel size must be between 0 and {MAX_PIXEL_SIZE:g} microns.")
    qe = data["qe"]
    if qe is None or not 0 < qe <= 1:
        errors.append("Quantum efficiency must be a fraction greater than 0 and at most 1 "
                      "(for example 0.8 for 80%).")
    return errors


def parse_xml(path):
    """Parse a camera data file into a dictionary, raising CameraDataError."""
    errors = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        raise CameraDataError([f"Not valid XML: {e}"])
    if root.tag != "ExposureCalculatorCameraData":
        raise CameraDataError(["The root element must be ExposureCalculatorCameraData."])

    for child in root:
        if child.tag not in ROOT_ELEMENTS:
            errors.append(f"Unknown element <{child.tag}>.")
    for tag in ROOT_ELEMENTS - {"CameraGainReadMode"}:
        if len(root.findall(tag)) != 1:
            errors.append(f"Exactly one <{tag}> element is required.")
    if errors:
        raise CameraDataError(errors)

    if root.findtext("CameraDataClassVersion").strip() != "1":
        errors.append("CameraDataClassVersion must be 1.")

    selections = []
    for element in root.find("CameraGainSelections"):
        if element.tag != "GainSelection":
            errors.append(f"Unknown element <{element.tag}> in <CameraGainSelections>.")
            continue
        value = _parse_int(element.text, "GainSelection", errors)
        if value is not None:
            selections.append(value)

    # KStars accepts two layouts: one <CameraGainReadMode> per mode, or several
    # number / name / table groups inside a single <CameraGainReadMode>. A
    # table always belongs to the number and name that precede it.
    modes = []
    for read_mode in root.findall("CameraGainReadMode"):
        number, name = None, ""
        for element in read_mode:
            if element.tag not in READ_MODE_ELEMENTS:
                errors.append(f"Unknown element <{element.tag}> in <CameraGainReadMode>.")
            elif element.tag == "GainReadModeNumber":
                number = _parse_int(element.text, "GainReadModeNumber", errors)
            elif element.tag == "GainReadModeName":
                name = (element.text or "").strip()
            else:
                table = []
                for value in element:
                    if value.tag != "GainReadNoiseValue":
                        errors.append(f"Unknown element <{value.tag}> in <CameraGainReadNoise>.")
                        continue
                    gain = _parse_int(value.findtext("Gain"), "Gain", errors)
                    read_noise = _parse_float(value.findtext("ReadNoise"), "ReadNoise", errors)
                    if gain is not None and read_noise is not None:
                        table.append((gain, read_noise))
                if number is None:
                    errors.append("A read-noise table has no GainReadModeNumber before it.")
                modes.append({"number": number, "name": name, "table": table})

    data = {
        "camera_id": (root.findtext("CameraId") or "").strip(),
        "sensor_type": root.findtext("SensorType").strip(),
        "gain_type": root.findtext("GainSelectionType").strip(),
        "gain_selections": selections,
        "modes": modes,
        "pixel_size": _parse_float(root.findtext("CameraPixelSize"), "CameraPixelSize", errors),
        "qe": _parse_float(root.findtext("CameraQuantumEfficiency"), "CameraQuantumEfficiency",
                           errors),
    }
    if errors:
        raise CameraDataError(errors)
    return data


def validate_file(path):
    """Return a list of problems with the camera data file at path."""
    try:
        data = parse_xml(path)
    except CameraDataError as e:
        return e.errors
    errors = check_data(data)
    expected = camera_id_to_file_name(data["camera_id"])
    if os.path.basename(path) != expected:
        errors.append(f"CameraId '{data['camera_id']}' does not match the file name; "
                      f"the file should be named '{expected}'.")
    return errors


def _format_number(value):
    return f"{value:g}"


def to_xml(data):
    """Return the canonical XML text for a camera data dictionary."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<ExposureCalculatorCameraData>",
        "    <CameraDataClassVersion>1</CameraDataClassVersion>",
        f"    <CameraId>{data['camera_id']}</CameraId>",
        f"    <SensorType>{data['sensor_type']}</SensorType>",
        f"    <GainSelectionType>{data['gain_type']}</GainSelectionType>",
        "    <CameraGainSelections>",
    ]
    lines += [f"        <GainSelection>{value}</GainSelection>" for value in data["gain_selections"]]
    lines.append("    </CameraGainSelections>")
    for index, mode in enumerate(data["modes"]):
        lines += [
            "    <CameraGainReadMode>",
            f"        <GainReadModeNumber>{index}</GainReadModeNumber>",
            f"        <GainReadModeName>{_escape(mode['name'])}</GainReadModeName>",
            "        <CameraGainReadNoise>",
        ]
        for gain, read_noise in mode["table"]:
            lines += [
                "            <GainReadNoiseValue>",
                f"                <Gain>{gain}</Gain>",
                f"                <ReadNoise>{_format_number(read_noise)}</ReadNoise>",
                "            </GainReadNoiseValue>",
            ]
        lines += ["        </CameraGainReadNoise>", "    </CameraGainReadMode>"]
    lines += [
        f"    <CameraPixelSize>{_format_number(data['pixel_size'])}</CameraPixelSize>",
        f"    <CameraQuantumEfficiency>{_format_number(data['qe'])}</CameraQuantumEfficiency>",
        "</ExposureCalculatorCameraData>",
        "",
    ]
    return "\n".join(lines)


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Issue form parsing --------------------------------------------------------

# Headings of the issue form fields, as GitHub renders them in the issue body.
FIELD_CAMERA_ID = "Camera name"
FIELD_SENSOR = "Sensor type"
FIELD_GAIN_TYPE = "Gain control"
FIELD_GAIN_RANGE = "Gain range or ISO values"
FIELD_PIXEL_SIZE = "Pixel size (microns)"
FIELD_QE = "Quantum efficiency"
FIELD_READ_NOISE = "Read noise"

SENSOR_CHOICES = {"Monochrome": "MONOCHROME", "Color": "COLOR"}
GAIN_CHOICES = {
    "Adjustable gain (most CMOS cameras)": "NORMAL",
    "ISO (DSLR and mirrorless cameras)": "ISO_DISCRETE",
    "Fixed, read noise does not depend on gain (CCD cameras)": "FIXED",
}
NO_RESPONSE = "_No response_"
MODE_HEADER_RE = re.compile(r"^\[(.+)\]$")


def parse_issue_sections(body):
    """Split a GitHub issue form body into {heading: value}."""
    sections = {}
    heading = None
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            heading = line[4:].strip()
            sections[heading] = []
        elif heading is not None:
            sections[heading].append(line)
    result = {}
    for key, lines in sections.items():
        value = "\n".join(lines).strip()
        # Text areas declared with "render" are wrapped in a code block.
        fence = re.match(r"^```[^\n]*\n(.*?)\n?```$", value, re.S)
        if fence:
            value = fence.group(1).strip()
        result[key] = "" if value == NO_RESPONSE else value
    return result


def _numbers(text, what, errors, parse):
    values = []
    for token in re.split(r"[,;\s]+", text.strip()):
        if token:
            value = parse(token, what, errors)
            if value is not None:
                values.append(value)
    return values


def parse_read_noise(text, gain_type, errors):
    """Parse read-noise lines into a list of modes."""
    modes = []
    current = None
    for line_number, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        header = MODE_HEADER_RE.match(line)
        if header:
            current = {"number": len(modes), "name": header.group(1).strip(), "table": []}
            modes.append(current)
            continue
        if current is None:
            current = {"number": 0, "name": "Standard", "table": []}
            modes.append(current)
        tokens = [token for token in re.split(r"[,;\s]+", line) if token]
        if gain_type == "FIXED" and len(tokens) == 1:
            tokens = ["0"] + tokens
        if len(tokens) != 2:
            errors.append(f"Read noise line {line_number} ('{line}') must contain a gain and a "
                          "read noise value, for example '100, 1.5'.")
            continue
        gain = _parse_int(tokens[0], f"The gain on read noise line {line_number}", errors)
        read_noise = _parse_float(tokens[1], f"The read noise on line {line_number}", errors)
        if gain is not None and read_noise is not None:
            current["table"].append((gain, read_noise))
    return modes


def data_from_issue(body):
    """Build a camera data dictionary from an issue form body."""
    sections = parse_issue_sections(body)
    errors = []
    for field in (FIELD_CAMERA_ID, FIELD_SENSOR, FIELD_GAIN_TYPE, FIELD_PIXEL_SIZE, FIELD_QE,
                  FIELD_READ_NOISE):
        if not sections.get(field):
            errors.append(f"The field '{field}' is missing.")
    if errors:
        raise CameraDataError(errors)

    camera_id = " ".join(sections[FIELD_CAMERA_ID].split())
    sensor_type = SENSOR_CHOICES.get(sections[FIELD_SENSOR])
    if sensor_type is None:
        errors.append(f"Unknown sensor type '{sections[FIELD_SENSOR]}'.")
    gain_type = GAIN_CHOICES.get(sections[FIELD_GAIN_TYPE])
    if gain_type is None:
        errors.append(f"Unknown gain control '{sections[FIELD_GAIN_TYPE]}'.")
        gain_type = "NORMAL"

    modes = parse_read_noise(sections[FIELD_READ_NOISE], gain_type, errors)

    if gain_type == "FIXED":
        # KStars draws the exposure graph between the first and last table
        # entries, so a fixed read noise is stored at gains -1 and 1, the same
        # as the existing CCD files.
        for mode in modes:
            if mode["table"]:
                read_noise = mode["table"][0][1]
                if any(value != read_noise for _, value in mode["table"]):
                    errors.append("A camera with fixed read noise must have a single read noise "
                                  "value per read mode.")
                mode["table"] = [(-1, read_noise), (1, read_noise)]
        selections = [0]
    else:
        selections = _numbers(sections.get(FIELD_GAIN_RANGE, ""), FIELD_GAIN_RANGE, errors,
                              _parse_int)
        all_gains = sorted({gain for mode in modes for gain, _ in mode["table"]})
        if not selections and all_gains:
            selections = [all_gains[0], all_gains[-1]] if gain_type == "NORMAL" else all_gains

    qe_text = sections[FIELD_QE].strip().rstrip("%").strip()
    qe = _parse_float(qe_text, FIELD_QE, errors)
    if qe is not None and qe > 1:
        qe = qe / 100.0

    data = {
        "camera_id": camera_id,
        "sensor_type": sensor_type or "",
        "gain_type": gain_type,
        "gain_selections": selections,
        "modes": modes,
        "pixel_size": _parse_float(sections[FIELD_PIXEL_SIZE], FIELD_PIXEL_SIZE, errors),
        "qe": qe,
    }
    if errors:
        raise CameraDataError(errors)
    errors = check_data(data)
    if errors:
        raise CameraDataError(errors)
    return data


# Command line --------------------------------------------------------------

def _default_files():
    here = os.path.dirname(os.path.abspath(__file__))
    return sorted(glob.glob(os.path.join(here, "..", "cameras", "*.xml")))


def command_validate(files):
    failed = 0
    for path in files or _default_files():
        errors = validate_file(path)
        if errors:
            failed += 1
            print(f"{path}:")
            for error in errors:
                print(f"  - {error}")
    count = len(files or _default_files())
    print(f"{count - failed} of {count} files valid.")
    return 1 if failed else 0


def command_normalize(files):
    for path in files or _default_files():
        data = parse_xml(path)
        data["camera_id"] = file_name_to_camera_id(path)
        with open(path, "w", encoding="utf-8") as f:
            f.write(to_xml(data))
    return 0


def _write_output(output, values):
    if output:
        with open(output, "a", encoding="utf-8") as f:
            for key, value in values.items():
                f.write(f"{key}={value}\n")


def command_from_issue(body_file, out_dir, output, errors_file):
    with open(body_file, encoding="utf-8") as f:
        body = f.read()
    try:
        data = data_from_issue(body)
    except CameraDataError as e:
        message = "\n".join(f"- {error}" for error in e.errors)
        print(message, file=sys.stderr)
        if errors_file:
            with open(errors_file, "w", encoding="utf-8") as f:
                f.write(message + "\n")
        return 1
    file_name = camera_id_to_file_name(data["camera_id"])
    path = os.path.join(out_dir, file_name)
    existed = os.path.exists(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_xml(data))
    print(f"Wrote {path}")
    _write_output(output, {"file": path, "camera": data["camera_id"],
                           "action": "Update" if existed else "Add"})
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate camera data files")
    validate.add_argument("files", nargs="*")
    normalize = sub.add_parser("normalize", help="rewrite files in canonical form")
    normalize.add_argument("files", nargs="*")
    issue = sub.add_parser("from-issue", help="generate a file from an issue form body")
    issue.add_argument("--body-file", required=True)
    issue.add_argument("--out-dir", required=True)
    issue.add_argument("--output", help="append key=value results to this file")
    issue.add_argument("--errors-file", help="write validation errors to this file")
    args = parser.parse_args(argv)

    if args.command == "validate":
        return command_validate(args.files)
    if args.command == "normalize":
        return command_normalize(args.files)
    return command_from_issue(args.body_file, args.out_dir, args.output, args.errors_file)


if __name__ == "__main__":
    sys.exit(main())
