import traceback
import time

from fgi.apk import APK
from fgi.arguments import Arguments
from fgi.cache import Cache
from fgi.frida_config import CONFIG_TYPES
from fgi.library import Library
from fgi.logger import Logger
from fgi.manifest import Manifest
from fgi.smali import Smali


class App:
    def run(self):
        start_time = time.time()
        
        arguments = Arguments.create()

        Logger.initialize(arguments.verbose)

        arguments.validate()

        cache = Cache()
        cache.ensure()

        if not arguments.offline_mode:
            cache.check_and_download_frida()
            cache.check_and_download_apkeditor()
        else:
            Logger.warn("Skipping update check for deps")

        Logger.info("🚀 Starting APK patching with Frida Gadget...")

        loader_type = arguments.pick_loader()
        loader = loader_type(cache.get_apkeditor_path(), arguments.input, arguments.temp_root_path)
        loader.load()
        
        # Create APK instance with optimization enabled
        apk = APK(cache.get_apkeditor_path(), arguments, loader)
        
        # Decode APK with optimization
        apk.decode()

        entrypoint = apk.get_entry_activity()
        
        # Perform Smali injection for Frida Gadget loading
        smali_injection_performed = False
        try:
            smali = Smali.find(apk.temp_path, entrypoint)
            Logger.info("🔍 Injecting Frida Gadget into Smali...")
            smali.perform_injection(arguments.library_name)
            smali_injection_performed = True
            del smali
            Logger.info("✅ Smali injection completed")
        except RuntimeError as e:
            Logger.warn(f"⚠️ Primary injection failed: {e}")
            
            # Try alternative injection targets
            try:
                alternative_targets = ["UnityPlayerActivity", "UnityPlayer", "MainActivity", "LauncherActivity"]
                
                for target in alternative_targets:
                    try:
                        smali_files = list(apk.temp_path.rglob("*.smali"))
                        for smali_file in smali_files:
                            if target in smali_file.name:
                                Logger.info(f"🎯 Using alternative target: {smali_file.name}")
                                smali = Smali(smali_file)
                                smali.perform_injection(arguments.library_name)
                                smali_injection_performed = True
                                del smali
                                Logger.info("✅ Alternative injection completed")
                                break
                        if smali_injection_performed:
                            break
                    except Exception:
                        continue
                
                if not smali_injection_performed:
                    raise RuntimeError(f"All injection methods failed")
                    
            except Exception:
                raise RuntimeError(f"Smali injection failed - {e}")
        
        # Continue with Frida injection
        Logger.info("🔧 Injecting Frida Gadget libraries...")

        library = Library(
            arguments.library_name,
            arguments.architectures,
            cache.get_home_path(),
            apk.temp_path,
        )
        
        library.copy_frida()

        if arguments.is_builtin_config():
            library.copy_config(
                CONFIG_TYPES[arguments.config_type] % arguments.script_name if arguments.is_script_required() else CONFIG_TYPES[arguments.config_type]
            )
        else:
            with open(arguments.config_path, "r", encoding="utf8") as f:
                config = f.read()
                library.copy_config(config)

        if arguments.is_script_required():
            with open(arguments.script_path, "rb") as f:
                script = f.read()
                library.copy_script(arguments.script_name, script)
        del library

        manifest = Manifest(apk.temp_path / "AndroidManifest.xml")
        manifest.enable_extract_native_libs()
        del manifest

        # Build APK
        Logger.info("🔨 Building patched APK...")
        apk.build()
        apk.zipalign()
        if not cache.get_key_path().exists():
            apk.generate_debug_key(cache.get_key_path())
        apk.sign(cache.get_key_path())
        
        del apk
        del cache
        
        total_time = time.time() - start_time
        Logger.info(f"✅ APK patching completed in {total_time:.1f}s")
        Logger.info(f"📱 Output: {arguments.out}")


def main():
    app = App()
    try:
        app.run()
    except KeyboardInterrupt:
        Logger.warn("Aborting...")
    except (RuntimeError, AssertionError) as e:
        Logger.error(str(e))
    except Exception as e:
        Logger.error(f"Unexpected exception: {e}")
        Logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()
