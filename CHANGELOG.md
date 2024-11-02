# Changelog

Oct Nov 2, 2024
1. add missing git pull in get_repos

Oct Nov 1, 2024
1. update repos
2. rework get_repo
3. flutter 3.24.4

Oct 16, 2024
1. Flutter SDK 3.24.3
2. add sudo rm -rf to cleanup failed runs
3. flutter_workspace.py: chown -R logname at start; helps with failed runs

Sept 7, 2024
1. Flutter SDK 3.24.2

Sept 4, 2024
1. Python virtual env by default.  This means python3-venv is now a hard requirement.
2. for post chown use logname; resolves sudo su and not invoking with sudo
3. roll playx3d

Aug 17, 2024
1. maplibre - enable vulkan backend
2. move libcamera to master
3. add sentry-native to repos.json

Aug 9, 2024
1. Change flutter channel switch sequence
2. Change occurences of `master` to `main`
3. remove scripts that moved to meta-flutter tools
4. remove unused pubspec.py
5. make create_aot.py version independent

Aug 2, 2024
1. Fix for `ERROR: FormatException: Could not find an option named "target-os"`

Aug 1, 2024
1. Flutter SDK 3.22.3

June 27, 2024
1. Add maplibre platform
2. add zenity to runtime package list
3. change libcamera meson install from user to sudo

June 26, 2024
1. sort platforms.  Allows platforms prefixed with "_" to run first.
2. increase plugin flags for ivi-homescreen
3. add maplibre platform - wayland + no x11

Mar 11, 2024
1. ensure recipes are lowercase
2. remove trailing space on file patch line

Feb 21, 2024
1. rework create_recipes.py + roll_meta_flutter.py
   add output_path key to override location where recipe gets written
   add rdepends key which writes recipe RDEPENDS
2. skip projects with malformed pubspec.yaml

Feb 20, 2024
1. update to Flutter SDK 3.19.0.
2. flutter-engine patch required to for engine 3.19.0 to enablele impeller with embedder.
3. remove configs/flutter-apps.json.  Origin of truth is in meta-flutter.
4. tweaks to desktop-homescreen build config related to vNext.
5. flutter_workspace.py updates:
   git fetch --all prior to attempting to checkout.
   Run `chown -R $USER:$USER .` flutter-workspace as last step.
