import platform
import random
import shutil
import string
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any
import subprocess
import psutil

from fgi.arguments import Arguments
from fgi.cmd import run_command_and_check
from fgi.loaders.base import BaseLoader
from fgi.loaders.split import SplitAPKLoader
from fgi.logger import Logger
from fgi.utils.not_none import not_none


class APKProcessor:
    """Optimized APK processor with parallel capabilities and performance monitoring"""
    
    def __init__(self, apkeditor_path: Path):
        self.apkeditor_path = apkeditor_path
        self.performance_metrics: Dict[str, float] = {}
        self.process_lock = threading.Lock()
        
    def get_optimal_jvm_args(self, apk_size_mb: int) -> list[str]:
        """Get optimal JVM arguments based on APK size and system resources
        
        Note: All JVM flags used are compatible with Java 8+ to ensure
        broad compatibility across different Java versions.
        """
        # Get total system memory (not just available) for better heap sizing
        total_memory = psutil.virtual_memory().total // (1024 * 1024)  # MB
        available_memory = psutil.virtual_memory().available // (1024 * 1024)  # MB
        cpu_count = psutil.cpu_count()
        
        if total_memory is None or available_memory is None or cpu_count is None:
            # Fallback to conservative values if system info unavailable
            total_memory = 8192  # 8GB default
            available_memory = 2048  # 2GB default
            cpu_count = 4  # 4 cores default
            Logger.warn("⚠️  System info unavailable, using conservative optimization values")
        
        # Base JVM arguments
        base_args = [
            "-XX:+UseG1GC",
            "-XX:MaxGCPauseMillis=200",
            "-XX:+UseStringDeduplication",
            "-XX:+UseCompressedOops",
            "-XX:+UseCompressedClassPointers",
            "-XX:G1HeapRegionSize=16m",
        ]
        
        # Memory allocation based on APK size and total system memory
        if apk_size_mb > 500:  # Large APK
            heap_size = min(apk_size_mb * 4, total_memory // 4)
            base_args.extend([
                f"-Xmx{heap_size}m",
                f"-Xms{heap_size // 4}m",
            ])
        else:  # Small/medium APK
            heap_size = max(1536, min(apk_size_mb * 10, total_memory // 4))
            base_args.extend([
                f"-Xmx{heap_size}m",
                f"-Xms{heap_size // 3}m",
            ])
        
        # Thread optimization
        if cpu_count > 4:
            parallel_threads = cpu_count // 2
            conc_threads = max(1, cpu_count // 4)
            base_args.extend([
                f"-XX:ParallelGCThreads={parallel_threads}",
                f"-XX:ConcGCThreads={conc_threads}",
            ])
        
        # Add additional performance flags
        base_args.extend([
            "-XX:+TieredCompilation",
            "-XX:+HeapDumpOnOutOfMemoryError",
        ])
        
        # Add heap dump path for Windows systems
        if platform.system() == "Windows":
            heap_dump_path = "C:\\temp\\heapdump.hprof"
            base_args.extend([
                f"-XX:HeapDumpPath={heap_dump_path}",
            ])
        
        return base_args
    
    def run_apkeditor_with_optimization(self, command: str, input_path: Path, output_path: Path, 
                                       additional_args: Optional[list[str]] = None) -> str:
        """Run APKEditor with optimized parameters"""
        start_time = time.time()
        
        # Get APK size for optimization
        try:
            if input_path.is_file():
                # Input is a file (APK) - get its size
                apk_size = int(input_path.stat().st_size / (1024 * 1024))  # MB, converted to int
            elif input_path.is_dir():
                # Input is a directory (decoded APK) - estimate size based on original APK
                # For build operations, we don't need exact size, use a reasonable default
                apk_size = 100  # Default size for build operations
                Logger.debug(f"🔍 Input is directory, using default APK size: {apk_size}MB")
            else:
                # Fallback for unknown path types
                apk_size = 100  # Default size
                Logger.warn(f"⚠️  Unknown input path type, using default APK size: {apk_size}MB")
        except OSError:
            apk_size = 100  # Default size
            Logger.warn(f"⚠️  Could not determine APK size, using default: {apk_size}MB")
        
        # Get optimal JVM arguments
        jvm_args = self.get_optimal_jvm_args(apk_size)
        
        # Build command with optimizations
        cmd = ["java"] + jvm_args + [
            "-jar", str(self.apkeditor_path),
            command
        ]
        
        # Add command-specific optimizations
        if command == "d":  # Decode
            cmd.extend([
                "-i", str(input_path),
                "-o", str(output_path),
                "-f",
                "-load-dex", "1",
                "-comment-level", "basic",
                "-dex-lib", "internal",
                "-t", "xml",
                "-split-json",
            ])
        elif command == "b":  # Build
            cmd.extend([
                "-i", str(input_path),
                "-o", str(output_path),
                "-f",
            ])
        elif command == "info":
            cmd.extend([
                "-i", str(input_path),
            ])
        
        # Add additional arguments if provided
        if additional_args:
            cmd.extend(additional_args)
        
        try:
            # Run with timeout and memory monitoring
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout for complex APKs (increased from 5 minutes)
                check=True
            )
            
            execution_time = time.time() - start_time
            self.performance_metrics[f"{command}_{input_path.name}"] = execution_time
            
            Logger.info(f"✅ APKEditor {command} completed in {execution_time:.2f}s")
            return process.stdout
            
        except subprocess.TimeoutExpired:
            Logger.error(f"❌ APKEditor {command} timed out after 10 minutes")
            raise RuntimeError(f"APKEditor {command} operation timed out")
        except subprocess.CalledProcessError as e:
            Logger.error(f"❌ APKEditor {command} failed: {e.stderr}")
            
            # Check if it's a memory error and suggest fallback
            if "OutOfMemoryError" in e.stderr or "Java heap space" in e.stderr:
                Logger.error("💡 OutOfMemoryError detected! This APK requires more memory than allocated.")
                Logger.error("💡 Consider using a machine with more RAM or try the jf DEX library fallback.")
            
            raise RuntimeError(f"APKEditor {command} failed: {e.stderr}")
    
    def get_performance_summary(self) -> str:
        """Get performance metrics summary"""
        if not self.performance_metrics:
            return "No performance data available"
        
        total_time = sum(self.performance_metrics.values())
        avg_time = total_time / len(self.performance_metrics)
        
        summary = f"📊 Performance Summary:\n"
        summary += f"⏱️  Total time: {total_time:.2f}s | Operations: {len(self.performance_metrics)}\n"
        summary += f"📈 Average: {avg_time:.2f}s per operation\n"
        
        for operation, time_taken in self.performance_metrics.items():
            summary += f"  • {operation}: {time_taken:.2f}s\n"
        
        return summary


class APK:
    def __init__(self, apkeditor_path: Path, arguments: Arguments, loader: BaseLoader):
        self.apkeditor_path = apkeditor_path
        self.arguments = arguments
        self.loader = loader
        self.temp_path = self.arguments.temp_root_path / "".join(random.choices(string.ascii_letters, k=12))
        self.processor = APKProcessor(apkeditor_path)
        
        # Create cache directory for performance optimization
        self.cache_dir = self.arguments.temp_root_path / "cache"
        self.cache_dir.mkdir(exist_ok=True)
        
        # Clear cache if force-fresh is enabled
        if self.arguments.force_fresh:
            Logger.info("🧹 Force-fresh enabled - clearing cache directory")
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(exist_ok=True)

    @property
    def _built_apk_path(self):
        return self.arguments.temp_root_path / (self.loader.source.absolute().name + "-built")

    @property
    def _zipaligned_apk_path(self):
        return self.arguments.temp_root_path / (self.loader.source.absolute().name + "-zipaligned")

    @property
    def _signed_apk_path(self):
        return self.arguments.temp_root_path / (self.loader.source.absolute().name + "-signed")

    def decode(self):
        Logger.info(f"Decoding APK to {self.temp_path}...")
        
        # Check if we can use cached decompilation
        cache_key = f"decode_{self.loader.output_path.name}_{self.loader.output_path.stat().st_mtime}"
        cache_file = self.cache_dir / f"{cache_key}.cache"
        
        if cache_file.exists() and self.arguments.use_cache and not self.arguments.force_fresh:
            Logger.info("📋 Using cached decompilation...")
            # Restore from cache
            shutil.copytree(cache_file, self.temp_path, dirs_exist_ok=True)
            
            # Verify cache integrity - check if Smali files exist
            smali_dirs = ["smali", "smali_classes2", "smali_classes3", "smali_classes4", "smali_classes5", "smali_classes6"]
            total_smali_files = 0
            for dir_name in smali_dirs:
                smali_dir = self.temp_path / dir_name
                if smali_dir.exists():
                    smali_files = list(smali_dir.rglob("*.smali"))
                    total_smali_files += len(smali_files)
            
            if total_smali_files == 0:
                Logger.warn("⚠️ Cache corrupted - forcing fresh decompilation")
                # Remove corrupted cache
                if cache_file.exists():
                    shutil.rmtree(cache_file, ignore_errors=True)
                # Force fresh decompilation
                Logger.info("🔄 Running fresh decompilation...")
                start_time = time.time()
                _ = self.processor.run_apkeditor_with_optimization(
                    "d", 
                    self.loader.output_path, 
                    self.temp_path
                )
                
                # Cache the fresh result
                if self.arguments.use_cache:
                    try:
                        shutil.copytree(self.temp_path, cache_file, dirs_exist_ok=True)
                    except Exception as e:
                        Logger.warn(f"Failed to cache: {e}")
                
                decode_time = time.time() - start_time
                Logger.info(f"✅ Decompiled in {decode_time:.1f}s")
                return
            else:
                return
        
        # Perform decompilation
        Logger.info("🔄 Decompiling APK...")
        start_time = time.time()
        _ = self.processor.run_apkeditor_with_optimization(
            "d", 
            self.loader.output_path, 
            self.temp_path
        )
        
        # Cache the result if caching is enabled
        if self.arguments.use_cache:
            try:
                shutil.copytree(self.temp_path, cache_file, dirs_exist_ok=True)
            except Exception as e:
                Logger.warn(f"Failed to cache: {e}")
        
        decode_time = time.time() - start_time
        Logger.info(f"✅ Decompiled in {decode_time:.1f}s")

    def build(self):
        Logger.info("🔨 Building APK...")
        
        start_time = time.time()
        _ = self.processor.run_apkeditor_with_optimization(
            "b", 
            self.temp_path, 
            self._built_apk_path
        )
        
        build_time = time.time() - start_time
        Logger.info(f"✅ Built in {build_time:.1f}s")

    def zipalign(self):
        Logger.info("📦 Zipaligning...")
        
        start_time = time.time()
        _ = run_command_and_check(
            [
                "zipalign",
                "-p",
                "4",
                self._built_apk_path,
                self._zipaligned_apk_path,
            ]
        )
        
        zipalign_time = time.time() - start_time
        Logger.info(f"✅ Zipaligned in {zipalign_time:.1f}s")
        
        self._built_apk_path.unlink()

    def generate_debug_key(self, key_path: Path):
        Logger.debug("🔑 Generating key...")
        _ = run_command_and_check(
            [
                "keytool",
                "-genkey",
                "-v",
                "-keystore",
                key_path,
                "-storepass",
                "android",
                "-alias",
                "androiddebugkey",
                "-keypass",
                "android",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-dname",
                "C=US, O=Android, CN=Android Debug",
            ]
        )

    def sign(self, key_path: Path):
        Logger.info("✍️ Signing APK...")
        
        start_time = time.time()
        # Move APK to track stage if any error
        shutil.move(self._zipaligned_apk_path, self._signed_apk_path)

        apksigner_executable = "apksigner"

        if platform.system() == "Windows":
            apksigner_executable += ".bat"

        _ = run_command_and_check(
            [
                apksigner_executable,
                "sign",
                "--ks",
                key_path,
                "--ks-pass",
                "pass:android",
                "--ks-key-alias",
                "androiddebugkey",
                self._signed_apk_path,
            ]
        )
        
        sign_time = time.time() - start_time
        Logger.info(f"✅ Signed in {sign_time:.1f}s")
        
        shutil.move(
            self._signed_apk_path,
            not_none(self.arguments.out),  # pyright: ignore[reportArgumentType]
        )  # XXX: assume that everything is ready

    def get_entry_activity(self):
        Logger.info("🔍 Getting entry activity...")
        output = self.processor.run_apkeditor_with_optimization(
            "info",
            self.loader.output_path,
            Path(""),  # No output needed for info
            ["-activities"]
        )
        
        if isinstance(self.loader, SplitAPKLoader):
            # Now we can safely remove merged APK
            self.loader.output_path.unlink()
            
        entrypoints = output.strip().replace("activity-main=", "").replace('"', "")
        assert entrypoints is not None, "No entrypoint(s) found :("
        return entrypoints

    def get_performance_summary(self) -> str:
        """Get performance summary for this APK processing session"""
        return self.processor.get_performance_summary()

    def __del__(self):
        if not self.arguments.no_cleanup and self.temp_path.exists():
            shutil.rmtree(self.temp_path)
        # GC everything if program died before GC in function
        if isinstance(self.loader, SplitAPKLoader) and self.loader.merge_temp_path.exists():
            shutil.rmtree(self.loader.merge_temp_path)
        self._built_apk_path.unlink(True)
        self._zipaligned_apk_path.unlink(True)
        self._signed_apk_path.unlink(True)
