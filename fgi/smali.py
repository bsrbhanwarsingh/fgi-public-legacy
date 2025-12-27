from pathlib import Path

from fgi.constants import SMALI_FULL_LOAD_LIBRARY, SMALI_PARTIAL_LOAD_LIBRARY
from fgi.logger import Logger


class Smali:
    def __init__(self, path: Path):
        self.path = path
        with open(self.path, "r", encoding="utf8") as f:
            self.content = f.readlines()

    @staticmethod
    def find(temp_path: Path, entrypoint: str):
        target_smali = entrypoint.split(".")[-1] + ".smali"
        package_path = entrypoint.replace(".", "/")

        Logger.info(f"Looking for {target_smali}...")
        Logger.info(f"Package path: {package_path}")

        # Check all possible Smali directories
        smali_dirs = ["smali", "smali_classes2", "smali_classes3", "smali_classes4", "smali_classes5", "smali_classes6"]
        
        # First, try exact package path in all directories
        for dir_name in smali_dirs:
            smali_dir = temp_path / dir_name
            if smali_dir.exists():
                exact_path = smali_dir / package_path / target_smali
                if exact_path.exists():
                    Logger.info(f"✅ Found at exact path")
                    return Smali(exact_path)
        
        # If exact path not found, search by filename in all directories
        Logger.info("🔍 Searching by filename...")
        for dir_name in smali_dirs:
            smali_dir = temp_path / dir_name
            if smali_dir.exists():
                for child in smali_dir.rglob("*"):
                    if child.name == target_smali:
                        Logger.info(f"✅ Found by filename")
                        return Smali(child)
        
        # If still not found, search for Unity patterns in all directories
        Logger.info("🔍 Searching for Unity activities...")
        unity_patterns = [
            "UnityPlayer", "UnityActivity", "MessagingUnityPlayer", "Unity",
            "Firebase", "Messaging", "Player", "Activity", "Main"
        ]
        
        for dir_name in smali_dirs:
            smali_dir = temp_path / dir_name
            if smali_dir.exists():
                for child in smali_dir.rglob("*"):
                    if child.name.endswith(".smali"):
                        for pattern in unity_patterns:
                            if pattern in child.name:
                                Logger.info(f"✅ Found Unity activity")
                                return Smali(child)
        
        # Last resort: show what Smali files exist for debugging
        Logger.info("❌ No Unity activities found")
        total_smali_files = 0
        
        # Count total Smali files for debugging
        for dir_name in smali_dirs:
            smali_dir = temp_path / dir_name
            if smali_dir.exists():
                smali_files = list(smali_dir.rglob("*.smali"))
                total_smali_files += len(smali_files)
        
        Logger.info(f"📊 Total .smali files: {total_smali_files}")
        
        raise RuntimeError(f"Couldn't find smali containing entrypoint ({entrypoint})")

    def find_inject_point(self, start: int) -> int:
        pos = start
        in_annotation = False
        
        # Optimize by checking common patterns first
        common_patterns = [".locals", ".annotation", ".end annotation"]
        
        while pos + 1 < len(self.content):
            pos = pos + 1
            line = self.content[pos].strip()

            # skip empty lines
            if not line:
                continue

            # Fast pattern matching
            if any(pattern in line for pattern in common_patterns):
                if line.startswith(".locals "):
                    continue
                elif line.startswith(".annotation "):
                    in_annotation = True
                    continue
                elif line.startswith(".end annotation"):
                    in_annotation = False
                    continue
                elif in_annotation:
                    continue
                else:
                    return pos - 1

            # If not a common pattern, check if it's a valid injection point
            if not in_annotation and not line.startswith("."):
                return pos - 1
                
        raise RuntimeError("Failed to determine injection point")

    def find_end_of_method(self, start: int) -> int:
        # Optimize by searching backwards from a reasonable limit
        search_limit = min(start + 100, len(self.content))
        
        for i in range(start, search_limit):
            if ".end method" in self.content[i]:
                end_of_method = i - 1
                
                # Check if the method has a return type call
                if "return" in self.content[end_of_method]:
                    end_of_method -= 1
                
                return end_of_method
        
        # Fallback to original method if not found in reasonable range
        end_methods = [(i + start) for i, x in enumerate(self.content[start:]) if ".end method" in x]
        
        if len(end_methods) <= 0:
            raise RuntimeError("Couldn't find the end of the existing constructor")

        end_of_method = end_methods[0] - 1

        # check if the constructor has a return type call. if it does,
        # move up one line again to inject our loadLibrary before the return
        if "return" in self.content[end_of_method]:
            end_of_method -= 1

        return end_of_method

    def put_load_library(self, library_name: str, marker: int):
        if "init" in self.content[marker]:
            Logger.debug("<init> is present in entry activity")

            inject_point = self.find_inject_point(marker)

            self.content = self.content[:inject_point] + (SMALI_PARTIAL_LOAD_LIBRARY % library_name).splitlines(keepends=True) + self.content[inject_point:]

        else:
            Logger.debug("<init> is NOT present in entry activity")

            self.content = self.content[:marker] + (SMALI_FULL_LOAD_LIBRARY % library_name).splitlines(keepends=True) + self.content[marker:]

    def update_locals(self, marker: int):
        end_of_method = self.find_end_of_method(marker)

        defined_locals = [i for i, x in enumerate(self.content[marker:end_of_method]) if ".locals" in x]

        if len(defined_locals) <= 0:
            Logger.warn("Couldn't determine any .locals for the target constructor")

        # determine the offset for the first matched .locals definition
        locals_smali_offset = defined_locals[0] + marker

        try:
            defined_local_value = self.content[locals_smali_offset].split(" ")[-1]
            defined_local_value_as_int = int(defined_local_value, 10)
            new_locals_value = defined_local_value_as_int + 1

        except ValueError:
            Logger.warn("Couldn't parse .locals value for the injected constructor")
            return

        self.content[locals_smali_offset] = self.content[locals_smali_offset].replace(str(defined_local_value_as_int), str(new_locals_value))

    def perform_injection(self, library_name: str):
        library_name = library_name.replace("lib", "").replace(".so", "")
        Logger.info(f'Injecting loadLibrary("{library_name}")')

        marker = [i for i, x in enumerate(self.content) if "# direct methods" in x]

        # ensure we got a marker
        if len(marker) <= 0:
            raise RuntimeError("Couldn't determine position to inject a loadLibrary call")

        # pick the first position for the inject. add one line as we
        # want to inject right below the comment we matched
        marker_value = marker[0] + 1

        self.put_load_library(library_name, marker_value)
        self.update_locals(marker_value)

    def __del__(self):
        try:
            with open(self.path, "w", encoding="utf8") as f:
                f.writelines(self.content)
        except IOError as e:
            Logger.error(f"Failed to write smali file {self.path}: {e}")
