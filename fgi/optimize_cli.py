"""
Command Line Interface for APKEditor Optimizer

This module provides a CLI for the APKEditor optimizer with commands for:
- Parallel processing
- Performance monitoring
- Cache management
- Optimization recommendations
"""

import argparse
import sys
from pathlib import Path
from typing import List

from fgi.apkeditor_optimizer import APKEditorOptimizer
from fgi.cache import Cache
from fgi.logger import Logger


def setup_logging(verbose: bool):
    """Setup logging based on verbosity level"""
    Logger.initialize(verbose)


def parallel_process_command(args):
    """Handle parallel processing command"""
    cache = Cache()
    cache.ensure()
    
    if not cache.get_apkeditor_path().exists():
        Logger.error("APKEditor not found. Please run the main tool first to download it.")
        return 1
    
    optimizer = APKEditorOptimizer(
        cache.get_apkeditor_path(),
        max_workers=args.max_workers
    )
    
    # Convert input paths to Path objects
    input_paths = [Path(p) for p in args.input]
    
    # Validate input paths
    for path in input_paths:
        if not path.exists():
            Logger.error(f"Input path does not exist: {path}")
            return 1
    
    Logger.info(f"Starting parallel processing of {len(input_paths)} APKs")
    
    try:
        if args.operation == "decode":
            results = optimizer.parallel_decode_apks(input_paths, args.output_dir)
            Logger.info(f"Successfully decoded {len(results)} APKs")
            
            if args.optimize_resources:
                for decoded_path in results.values():
                    optimizer.optimize_resources(decoded_path)
                Logger.info("Resources optimized for all decoded APKs")
                
        elif args.operation == "build":
            results = optimizer.parallel_build_apks(input_paths, args.output_dir)
            Logger.info(f"Successfully built {len(results)} APKs")
        
        # Show performance summary
        stats = optimizer.get_performance_stats()
        Logger.info("Performance Summary:")
        for key, value in stats.items():
            if isinstance(value, float):
                Logger.info(f"  {key}: {value:.2f}")
            else:
                Logger.info(f"  {key}: {value}")
        
        # Show optimization recommendations
        recommendations = optimizer.get_optimization_recommendations()
        if recommendations:
            Logger.info("Optimization Recommendations:")
            for rec in recommendations:
                Logger.info(f"  - {rec}")
        
        return 0
        
    except Exception as e:
        Logger.error(f"Parallel processing failed: {e}")
        return 1


def performance_command(args):
    """Handle performance monitoring command"""
    cache = Cache()
    cache.ensure()
    
    if not cache.get_apkeditor_path().exists():
        Logger.error("APKEditor not found. Please run the main tool first to download it.")
        return 1
    
    optimizer = APKEditorOptimizer(cache.get_apkeditor_path())
    
    if args.clear_cache:
        optimizer.clear_cache()
        Logger.info("Performance cache cleared")
        return 0
    
    stats = optimizer.get_performance_stats()
    
    if "message" in stats:
        Logger.info(stats["message"])
        return 0
    
    Logger.info("Performance Statistics:")
    Logger.info("=" * 50)
    
    # Basic stats
    Logger.info(f"Total Operations: {stats['total_operations']}")
    Logger.info(f"Successful: {stats['successful_operations']}")
    Logger.info(f"Failed: {stats['failed_operations']}")
    Logger.info(f"Success Rate: {stats['success_rate']:.1f}%")
    
    # Timing stats
    if 'decode_time_avg' in stats:
        Logger.info(f"\nDecode Operations: {stats['decode_operations']}")
        Logger.info(f"  Average Time: {stats['decode_time_avg']:.2f}s")
        Logger.info(f"  Min Time: {stats['decode_time_min']:.2f}s")
        Logger.info(f"  Max Time: {stats['decode_time_max']:.2f}s")
    
    if 'build_time_avg' in stats:
        Logger.info(f"\nBuild Operations: {stats['build_operations']}")
        Logger.info(f"  Average Time: {stats['build_time_avg']:.2f}s")
        Logger.info(f"  Min Time: {stats['build_time_min']:.2f}s")
        Logger.info(f"  Max Time: {stats['build_time_max']:.2f}s")
    
    # Recommendations
    recommendations = optimizer.get_optimization_recommendations()
    if recommendations:
        Logger.info(f"\nOptimization Recommendations:")
        for i, rec in enumerate(recommendations, 1):
            Logger.info(f"  {i}. {rec}")
    
    return 0


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="APKEditor Optimizer CLI - Speed up APK decompilation and recompilation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parallel decode multiple APKs
  python -m fgi.optimize_cli parallel decode -i app1.apk app2.apk -o ./decoded/ --max-workers 4
  
  # Parallel build multiple decoded APKs
  python -m fgi.optimize_cli parallel build -i ./decoded/app1 ./decoded/app2 -o ./built/ --max-workers 4
  
  # Show performance statistics
  python -m fgi.optimize_cli performance
  
  # Clear performance cache
  python -m fgi.optimize_cli performance --clear-cache
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Parallel processing command
    parallel_parser = subparsers.add_parser('parallel', help='Parallel processing operations')
    parallel_parser.add_argument('operation', choices=['decode', 'build'], help='Operation to perform')
    parallel_parser.add_argument('-i', '--input', nargs='+', required=True, help='Input APK files or directories')
    parallel_parser.add_argument('-o', '--output-dir', type=Path, required=True, help='Output directory')
    parallel_parser.add_argument('--max-workers', type=int, default=None, help='Maximum number of parallel workers')
    parallel_parser.add_argument('--optimize-resources', action='store_true', help='Optimize resources after decode')
    
    # Performance command
    perf_parser = subparsers.add_parser('performance', help='Performance monitoring and cache management')
    perf_parser.add_argument('--clear-cache', action='store_true', help='Clear performance cache')
    
    # Global options
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Setup logging
    setup_logging(args.verbose)
    
    try:
        if args.command == 'parallel':
            return parallel_process_command(args)
        elif args.command == 'performance':
            return performance_command(args)
        else:
            Logger.error(f"Unknown command: {args.command}")
            return 1
            
    except KeyboardInterrupt:
        Logger.warn("Operation interrupted by user")
        return 1
    except Exception as e:
        Logger.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback
            Logger.error(traceback.format_exc())
        return 1


if __name__ == '__main__':
    sys.exit(main())
