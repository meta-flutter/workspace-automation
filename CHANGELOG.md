# Changelog

Feb 21, 2024
1. rework create_recipes.py + roll_meta_flutter.py
   add output_path key to override location where recipe gets written
   add rdepends key which writes recipe RDEPENDS

Feb 20, 2024
1. update to Flutter SDK 3.19.0.
2. flutter-engine patch required to for engine 3.19.0 to enablele impeller with embedder.
3. remove configs/flutter-apps.json.  Origin of truth is in meta-flutter.
4. tweaks to desktop-homescreen build config related to vNext.
5. flutter_workspace.py updates:
   git fetch --all prior to attempting to checkout.
   Run `chown -R $USER:$USER .` flutter-workspace as last step.