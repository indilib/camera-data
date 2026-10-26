# Camera Data for the KStars Exposure Calculator

This repository holds the camera read noise data used by the
[Exposure Calculator](https://kstars-docs.kde.org/en/user_manual/ekos-capture.html#exposure-calculator)
in KStars/Ekos. The calculator uses it to suggest the best sub-exposure time and gain for your camera,
sky and telescope.

KStars ships with a copy of these files. To get cameras added after your KStars release, open the
Exposure Calculator and click **+** next to the camera selector.

## Add your camera

**[Open the camera form](https://github.com/indilib/camera-data/issues/new?template=camera.yml)**. No XML or
git is needed.

You fill in a few values, which you can usually find on the manufacturer's product page:

- the camera name as Ekos shows it, for example `ZWO CCD ASI2600MM Pro`,
- mono or color sensor, and how gain is set (adjustable gain, ISO, or fixed for CCD cameras),
- pixel size and peak quantum efficiency,
- the read noise chart, as `gain, read noise` lines.

When you submit, a bot checks your values and opens a pull request with the camera data file. If something is
wrong, the bot comments on your issue: edit the issue and the check runs again. A maintainer reviews the pull
request, and once it is merged, KStars users can download your camera from the Exposure Calculator.

To correct an existing camera, submit the form again with the same camera name.

### Measured values

Manufacturer charts are a good start, but your own camera may differ. If you measured your camera, for example
with the SharpCap sensor analysis tool, use those values and say so in the **Source** field.

## File format

Each camera is one XML file in [`cameras/`](cameras). The file name is the camera name as Ekos shows it, with
spaces replaced by underscores: `ZWO CCD ASI2600MM Pro` is stored in `ZWO_CCD_ASI2600MM_Pro.xml`. KStars selects
the file matching the active camera automatically.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ExposureCalculatorCameraData>
    <CameraDataClassVersion>1</CameraDataClassVersion>
    <CameraId>ZWO CCD ASI2600MM Pro</CameraId>
    <SensorType>MONOCHROME</SensorType>
    <GainSelectionType>NORMAL</GainSelectionType>
    <CameraGainSelections>
        <GainSelection>0</GainSelection>
        <GainSelection>460</GainSelection>
    </CameraGainSelections>
    <CameraGainReadMode>
        <GainReadModeNumber>0</GainReadModeNumber>
        <GainReadModeName>Standard</GainReadModeName>
        <CameraGainReadNoise>
            <GainReadNoiseValue>
                <Gain>0</Gain>
                <ReadNoise>3.5</ReadNoise>
            </GainReadNoiseValue>
            <!-- more gain / read noise pairs -->
        </CameraGainReadNoise>
    </CameraGainReadMode>
    <CameraPixelSize>3.76</CameraPixelSize>
    <CameraQuantumEfficiency>0.91</CameraQuantumEfficiency>
</ExposureCalculatorCameraData>
```

| Element | Meaning |
|---|---|
| `CameraDataClassVersion` | Always `1`. |
| `CameraId` | The camera name. Must match the file name. |
| `SensorType` | `MONOCHROME` or `COLOR`. |
| `GainSelectionType` | `NORMAL` (adjustable gain), `ISO_DISCRETE` (DSLR ISO values) or `FIXED` (CCD, read noise independent of gain). |
| `CameraGainSelections` | `NORMAL`: the minimum and maximum gain. `ISO_DISCRETE`: every selectable ISO value. `FIXED`: a single `0`. |
| `CameraGainReadMode` | One read noise table per read mode, numbered from 0, with a name. Most cameras have one mode. |
| `GainReadNoiseValue` | A gain (whole number) and its read noise in electrons, in increasing gain order. |
| `CameraPixelSize` | Pixel size in microns. |
| `CameraQuantumEfficiency` | Peak quantum efficiency as a fraction, for example `0.91`. |

Cameras with fixed read noise store the same value at gains `-1` and `1`.

### Rules

KStars does not check these files, so a mistake leads to wrong exposure times or a crash. Every pull request is
checked automatically:

- read modes are numbered 0, 1, 2… in order,
- gains are whole numbers in increasing order within each table,
- the file name matches `CameraId`, which may only contain letters, digits, spaces and `( ) + -`,
- read noise and pixel size are positive, quantum efficiency is between 0 and 1,
- no unknown elements.

To check files locally (Python 3, no extra packages):

```bash
python3 tools/camera_data.py validate
python3 -m unittest discover -s tests
```

Pull requests with hand-written files are welcome too. Run the checks above before submitting.

## For maintainers

- The `Camera data from issue` workflow needs **Settings → Actions → General → Allow GitHub Actions to create
  and approve pull requests** enabled, and the `camera-data` label.
- Pull requests opened by the workflow do not trigger the `Validate` workflow (a GitHub restriction on the
  built-in token), but the workflow validates the file before opening the pull request.
- KStars bundles these files in `kstars/data/cameradata`. Before a KStars release, sync them with
  `tools/sync_camera_data.sh` in the KStars repository.

## License

The camera data and tools are licensed under the GNU General Public License, version 2 or later, the same
license under which the data was originally published in KStars. See [LICENSE](LICENSE).
