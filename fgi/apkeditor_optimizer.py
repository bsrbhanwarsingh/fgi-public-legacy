"""
APKEditor Optimizer Module

This module provides advanced optimization features for APKEditor operations:
- Parallel processing for multiple APKs
- Incremental builds
- Resource optimization
- Memory management
- Performance monitoring
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import json
import hashlib
import shutil

from fgi.logger import Logger


class APKEditorOptimizer:
    """Advanced APKEditor optimizer with parallel processing and caching"""
    
    def __init__(self, apkeditor_path: Path, max_workers: Optional[int] = None):
        self.apkeditor_path = apkeditor_path
        self.max_workers = max_workers or min(4, os.cpu_count() or 4)
        self.cache_dir = Path.home() / ".fgi" / "apkeditor_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.performance_cache = self.cache_dir / "performance.json"
        self._load_performance_cache()
        
    def _load_performance_cache(self):
        """Load performance cache from disk"""
        if self.performance_cache.exists():
            try:
                with open(self.performance_cache, 'r') as f:
                    self.performance_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self.performance_data = {}
        else:
            self.performance_data = {}
    
    def _save_performance_cache(self):
        """Save performance cache to disk"""
        try:
            with open(self.performance_cache, 'w') as f:
                json.dump(self.performance_data, f, indent=2)
        except IOError:
            Logger.warn("Failed to save performance cache")
    
    def get_apk_fingerprint(self, apk_path: Path) -> str:
        """Generate fingerprint for APK based on size and modification time"""
        try:
            stat = apk_path.stat()
            # Use size and mtime for fingerprint
            fingerprint_data = f"{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(fingerprint_data.encode()).hexdigest()
        except OSError:
            return ""
    
    def should_skip_processing(self, apk_path: Path, operation: str) -> bool:
        """Check if processing can be skipped based on cache"""
        fingerprint = self.get_apk_fingerprint(apk_path)
        cache_key = f"{operation}_{fingerprint}"
        
        if cache_key in self.performance_data:
            cached_result = self.performance_data[cache_key]
            # Check if cached result is still valid (within 24 hours)
            if time.time() - cached_result.get("timestamp", 0) < 86400:
                return True
        
        return False
    
    def update_performance_cache(self, apk_path: Path, operation: str, 
                               execution_time: float, success: bool = True):
        """Update performance cache with operation results"""
        fingerprint = self.get_apk_fingerprint(apk_path)
        cache_key = f"{operation}_{fingerprint}"
        
        self.performance_data[cache_key] = {
            "timestamp": time.time(),
            "execution_time": execution_time,
            "success": success,
            "apk_size": apk_path.stat().st_size if apk_path.exists() else 0
        }
        self._save_performance_cache()
    
    def parallel_decode_apks(self, apk_paths: List[Path], output_dir: Path) -> Dict[Path, Path]:
        """Decode multiple APKs in parallel"""
        Logger.info(f"Starting parallel decode of {len(apk_paths)} APKs with {self.max_workers} workers")
        
        results = {}
        failed_apks = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all decode tasks
            future_to_apk = {
                executor.submit(self._decode_single_apk, apk_path, output_dir): apk_path
                for apk_path in apk_paths
            }
            
            # Process completed tasks
            for future in as_completed(future_to_apk):
                apk_path = future_to_apk[future]
                try:
                    output_path = future.result()
                    results[apk_path] = output_path
                    Logger.info(f"Successfully decoded {apk_path.name}")
                except Exception as e:
                    Logger.error(f"Failed to decode {apk_path.name}: {e}")
                    failed_apks.append(apk_path)
        
        if failed_apks:
            Logger.warn(f"Failed to decode {len(failed_apks)} APKs: {[apk.name for apk in failed_apks]}")
        
        return results
    
    def _decode_single_apk(self, apk_path: Path, output_dir: Path) -> Path:
        """Decode a single APK with optimization"""
        start_time = time.time()
        
        # Check if we can skip processing
        if self.should_skip_processing(apk_path, "decode"):
            Logger.debug(f"Skipping decode for {apk_path.name} (cached)")
            return output_dir / apk_path.stem
        
        # Create output directory
        output_path = output_dir / apk_path.stem
        output_path.mkdir(parents=True, exist_ok=True)
        
        try:
            # Run APKEditor decode with optimization
            cmd = [
                "java", "-jar", str(self.apkeditor_path),
                "d", "-i", str(apk_path), "-o", str(output_path),
                "-f", "-clean-meta"  # Force overwrite and clean metadata
            ]
            
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                raise RuntimeError(f"APKEditor decode failed: {result.stderr}")
            
            execution_time = time.time() - start_time
            self.update_performance_cache(apk_path, "decode", execution_time, True)
            
            Logger.debug(f"Decoded {apk_path.name} in {execution_time:.2f}s")
            return output_path
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.update_performance_cache(apk_path, "decode", execution_time, False)
            raise e
    
    def parallel_build_apks(self, decoded_paths: List[Path], output_dir: Path) -> Dict[Path, Path]:
        """Build multiple decoded APKs in parallel"""
        Logger.info(f"Starting parallel build of {len(decoded_paths)} APKs with {self.max_workers} workers")
        
        results = {}
        failed_builds = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all build tasks
            future_to_path = {
                executor.submit(self._build_single_apk, decoded_path, output_dir): decoded_path
                for decoded_path in decoded_paths
            }
            
            # Process completed tasks
            for future in as_completed(future_to_path):
                decoded_path = future_to_path[future]
                try:
                    output_path = future.result()
                    results[decoded_path] = output_path
                    Logger.info(f"Successfully built {decoded_path.name}")
                except Exception as e:
                    Logger.error(f"Failed to build {decoded_path.name}: {e}")
                    failed_builds.append(decoded_path)
        
        if failed_builds:
            Logger.warn(f"Failed to build {len(failed_builds)} APKs: {[path.name for path in failed_builds]}")
        
        return results
    
    def _build_single_apk(self, decoded_path: Path, output_dir: Path) -> Path:
        """Build a single decoded APK with optimization"""
        start_time = time.time()
        
        # Create output path
        output_path = output_dir / f"{decoded_path.name}-built.apk"
        
        try:
            # Run APKEditor build with optimization
            cmd = [
                "java", "-jar", str(self.apkeditor_path),
                "b", "-i", str(decoded_path), "-o", str(output_path),
                "-f"  # Force overwrite
            ]
            
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                raise RuntimeError(f"APKEditor build failed: {result.stderr}")
            
            execution_time = time.time() - start_time
            self.update_performance_cache(decoded_path, "build", execution_time, True)
            
            Logger.debug(f"Built {decoded_path.name} in {execution_time:.2f}s")
            return output_path
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.update_performance_cache(decoded_path, "build", execution_time, False)
            raise e
    
    def optimize_resources(self, decoded_path: Path) -> None:
        """Optimize resources in decoded APK for faster processing"""
        Logger.info(f"Optimizing resources in {decoded_path.name}")
        
        # Remove unnecessary files to speed up processing
        unnecessary_dirs = ["META-INF", "original", "unknown"]
        unnecessary_files = ["apktool.yml", "apktool.yml.bak"]
        
        for dir_name in unnecessary_dirs:
            dir_path = decoded_path / dir_name
            if dir_path.exists():
                shutil.rmtree(dir_path)
                Logger.debug(f"Removed unnecessary directory: {dir_name}")
        
        for file_name in unnecessary_files:
            file_path = decoded_path / file_name
            if file_path.exists():
                file_path.unlink()
                Logger.debug(f"Removed unnecessary file: {file_name}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics"""
        if not self.performance_data:
            return {"message": "No performance data available"}
        
        total_operations = len(self.performance_data)
        successful_operations = sum(1 for data in self.performance_data.values() if data.get("success", False))
        failed_operations = total_operations - successful_operations
        
        # Calculate timing statistics
        decode_times = [data["execution_time"] for data in self.performance_data.values() 
                       if data.get("success", False) and "decode" in list(self.performance_data.keys())[0]]
        build_times = [data["execution_time"] for data in self.performance_data.values() 
                      if data.get("success", False) and "build" in list(self.performance_data.keys())[0]]
        
        stats = {
            "total_operations": total_operations,
            "successful_operations": successful_operations,
            "failed_operations": failed_operations,
            "success_rate": (successful_operations / total_operations * 100) if total_operations > 0 else 0,
            "decode_operations": len([k for k in self.performance_data.keys() if "decode" in k]),
            "build_operations": len([k for k in self.performance_data.keys() if "build" in k]),
        }
        
        if decode_times:
            stats["decode_time_avg"] = sum(decode_times) / len(decode_times)
            stats["decode_time_min"] = min(decode_times)
            stats["decode_time_max"] = max(decode_times)
        
        if build_times:
            stats["build_time_avg"] = sum(build_times) / len(build_times)
            stats["build_time_min"] = min(build_times)
            stats["build_time_max"] = max(build_times)
        
        return stats
    
    def clear_cache(self) -> None:
        """Clear all cached data"""
        try:
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.performance_data = {}
            self._save_performance_cache()
            Logger.info("APKEditor cache cleared")
        except Exception as e:
            Logger.error(f"Failed to clear cache: {e}")
    
    def get_optimization_recommendations(self) -> List[str]:
        """Get recommendations for further optimization"""
        recommendations = []
        
        if self.max_workers < 4:
            recommendations.append("Consider increasing max_workers for better parallel processing")
        
        if len(self.performance_data) > 100:
            recommendations.append("Performance cache is large, consider clearing old entries")
        
        # Check for slow operations
        slow_threshold = 60  # 60 seconds
        slow_operations = [k for k, v in self.performance_data.items() 
                          if v.get("execution_time", 0) > slow_threshold]
        
        if slow_operations:
            recommendations.append(f"Found {len(slow_operations)} slow operations (>60s), consider optimizing large APKs")
        
        return recommendations
