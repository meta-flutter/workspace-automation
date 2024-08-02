# Changelog

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
