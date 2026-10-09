# Recordings of real Exta Life controllers

`synthetic_fake_controller.jsonl` is an example made with the fake controller used by tests - it documents the file
format and keeps the replay test running. Recordings of real installations are very welcome.

Every `*.jsonl` file in this directory is replayed by `tests/test_recordings.py`: the integration is set up against
a fake controller serving the recorded responses, all recorded notifications are sent and no errors may be logged.

## How to make a recording

1. In Home Assistant go to **Developer tools → Actions** and run `extalife.record_traffic` with the controller entity
   and duration in minutes (default 10).
2. While recording, use the devices you want to have covered: press remote buttons, switch lights, move covers,
   trigger scenes, open the Exta Life app.
3. When the time is up (or after running the action again with duration `0`) the file is saved to
   `config/extalife/recordings/` and a notification with its path is shown.

Login and password are removed from the recording. It still contains device names, serial numbers and the controller
network configuration - review it before publishing.
