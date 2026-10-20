[app]
title = InstaLockpick
package.name = instalockpick
package.domain = ai.venice
version = 0.1.0
source.dir = .
source.include_exts = py,png,jpg,kv
source.exclude_dirs = bin,.buildozer,__pycache__

requirements = python3,kivy==2.3.1,instaloader,requests,certifi,urllib3,pyjnius,androidstorage4kivy

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/presplash.png
android.presplash_color = #0E0E12

android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a
android.enable_androidx = True
android.accept_sdk_license = True
android.release_artifact = apk

p4a.bootstrap = sdl2
p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 0
