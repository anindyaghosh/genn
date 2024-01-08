import os
import sys
from copy import deepcopy
from glob import glob
from platform import system, uname
from shutil import copyfile, copytree, rmtree
from subprocess import check_call
from setuptools import find_packages, setup

# **HACK** to support two-pass setup.py
try:
    from psutil import cpu_count
except ImportError:
    pass

# **HACK** to support two-pass setup.py
try:
    from pybind11.setup_helpers import Pybind11Extension, build_ext, WIN, MACOS
except ImportError:
    from setuptools import build_ext
    from setuptools import Extension as Pybind11Extension
    WIN = False
    MACOS = False
    
# Determine is this is a debug build
# **YUCK** this is not a great test
debug_build = "--debug" in sys.argv

# Determine if this is a coverage build
if "--coverage" in sys.argv:
    coverage_build = True
    sys.argv.remove("--coverage")
else:
    coverage_build = False

# Get CUDA path from environment variable - setting this up is a required CUDA post-install step
cuda_path = os.environ.get("CUDA_PATH")

# Is CUDA installed?
cuda_installed = cuda_path is not None and os.path.exists(cuda_path)

# Get OpenCL path from environment variable
opencl_path = os.environ.get("OPENCL_PATH")

# Is OpenCL installed
opencl_installed = False #opencl_path is not None and os.path.exists(opencl_path)

# Are we on Linux?
# **NOTE** Pybind11Extension provides WIN and MAC
LINUX = system() == "Linux"

# Are we on WSL?
if sys.version_info < (3, 3):
    WSL = "microsoft" in uname()[2]
else:
    WSL = "microsoft" in uname().release

# Determine correct suffix for GeNN libraries
if WIN:
    genn_lib_suffix = "_Debug_DLL" if debug_build else "_Release_DLL"
else:
    if coverage_build:
        genn_lib_suffix = "_coverage_dynamic"
    elif debug_build:
        genn_lib_suffix = "_dynamic_debug"
    else:
        genn_lib_suffix = "_dynamic"

genn_path = os.path.dirname(os.path.abspath(__file__))

pygenn_path = os.path.join(genn_path, "pygenn")
pygenn_src = os.path.join(pygenn_path, "src")
pygenn_include = os.path.join(pygenn_path, "include")
genn_include = os.path.join(genn_path, "include", "genn", "genn")
genn_third_party_include = os.path.join(genn_path, "include", "genn", "third_party")
genn_share = os.path.join(genn_path, "share", "genn")
pygenn_share = os.path.join(pygenn_path, "share")


# Copy GeNN 'share' tree into pygenn and add all files to package
# **THINK** this could be done on a per-backend basis
package_data = []
rmtree(pygenn_share, ignore_errors=True)
copytree(genn_share, pygenn_share)
for root, _, filenames in os.walk(pygenn_share):
    for f in filenames:
        f_path = os.path.join(root, f)
        if os.path.isfile(f_path):
            package_data.append(f_path)

# Define standard kwargs for building all extensions
genn_extension_kwargs = {
    "include_dirs": [pygenn_include, genn_include, genn_third_party_include],
    "library_dirs": [],
    "libraries": ["genn" + genn_lib_suffix],
    "cxx_std": 17,
    "extra_compile_args": [],
    "extra_link_args": [],
    "define_macros": [("LINKING_GENN_DLL", 1), ("LINKING_BACKEND_DLL", 1)]}

# If this is Windows
if WIN:
    # Turn off warnings about dll-interface being required for stuff to be
    # used by clients and prevent windows.h exporting TOO many awful macros
    genn_extension_kwargs["extra_compile_args"].extend(["/wd4251", "-DWIN32_LEAN_AND_MEAN", "-DNOMINMAX"])

    # Add include directory for FFI as it's built from source
    genn_extension_kwargs["include_dirs"].append(os.path.join(genn_third_party_include, "libffi"))

    # Add FFI library with correct suffix
    # **TODO** just call this ffi
    genn_extension_kwargs["libraries"].append("libffi" + genn_lib_suffix)
# Otherwise
else:
    # If this is Linux, we want to add extension directory i.e. $ORIGIN to runtime
    # directories so libGeNN and backends can be found wherever package is installed
    if LINUX:
        genn_extension_kwargs["runtime_library_dirs"] = ["$ORIGIN"]
        genn_extension_kwargs["libraries"].append("ffi")

if coverage_build:
    if LINUX:
        genn_extension_kwargs["extra_compile_args"].append("--coverage")
        genn_extension_kwargs["extra_link_args"].append("--coverage")
    elif MAC:
        genn_extension_kwargs["extra_compile_args"].extend(["-fprofile-instr-generate", "-fcoverage-mapping"])

# By default build single-threaded CPU backend
backends = [("single_threaded_cpu", "singleThreadedCPU", {})]

# If CUDA was found, add backend configuration
if cuda_installed:
    # Get CUDA library directory
    cuda_library_dirs = []
    if MACOS:
        cuda_library_dirs.append(os.path.join(cuda_path, "lib"))
    elif WIN:
        cuda_library_dirs.append(os.path.join(cuda_path, "lib", "x64"))
    else:
        cuda_library_dirs.append(os.path.join(cuda_path, "lib64"))

    # If we're running on WSL, add additional library path so libcuda can be found
    if WSL:
        cuda_library_dirs.append("/usr/lib/wsl/lib")

    # Add backend
    # **NOTE** on Mac OS X, a)runtime_library_dirs doesn't work b)setting rpath is required to find CUDA
    backends.append(("cuda", "cuda",
                     {"libraries": ["cuda", "cudart"],
                      "include_dirs": [os.path.join(cuda_path, "include")],
                      "library_dirs": cuda_library_dirs,
                      "extra_link_args": ["-Wl,-rpath," + cuda_library_dirs[0]] if MACOS else []}))

# If OpenCL was found, add backend configuration
if opencl_installed:
    # Get OpenCL library directory
    if MACOS:
        raise NotImplementedError("Mac not currently supported")
    elif WIN:
        opencl_library_dir = os.path.join(opencl_path, "lib", "x64")
    else:
        opencl_library_dir = os.path.join(opencl_path, "lib64")

    # Add backend
    # **NOTE** on Mac OS X, a)runtime_library_dirs doesn't work b)setting rpath is required to find CUDA
    backends.append(("opencl", "opencl",
                     {"libraries": ["OpenCL"],
                      "include_dirs": [os.path.join(opencl_path, "include")],
                      "library_dirs": [opencl_library_dir],
                      "extra_link_args": ["-Wl,-rpath," + opencl_library_dir] if MACOS else [],
                      "extra_compile_args": ["-DCL_HPP_TARGET_OPENCL_VERSION=120", "-DCL_HPP_MINIMUM_OPENCL_VERSION=120"]}))

ext_modules = [
    Pybind11Extension("runtime",
                      [os.path.join(pygenn_src, "runtime.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("genn",
                      [os.path.join(pygenn_src, "genn.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("types",
                      [os.path.join(pygenn_src, "types.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("init_sparse_connectivity_snippets",
                      [os.path.join(pygenn_src, "initSparseConnectivitySnippets.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("init_toeplitz_connectivity_snippets",
                      [os.path.join(pygenn_src, "initToeplitzConnectivitySnippets.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("init_var_snippets",
                      [os.path.join(pygenn_src, "initVarSnippets.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("current_source_models",
                      [os.path.join(pygenn_src, "currentSourceModels.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("custom_connectivity_update_models",
                      [os.path.join(pygenn_src, "customConnectivityUpdateModels.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("custom_update_models",
                      [os.path.join(pygenn_src, "customUpdateModels.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("neuron_models",
                      [os.path.join(pygenn_src, "neuronModels.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("postsynaptic_models",
                      [os.path.join(pygenn_src, "postsynapticModels.cc")],
                      **genn_extension_kwargs),
    Pybind11Extension("weight_update_models",
                      [os.path.join(pygenn_src, "weightUpdateModels.cc")],
                      **genn_extension_kwargs)]

 # Loop through namespaces of supported backends
for module_stem, source_stem, kwargs in backends:
    # Take a copy of the standard extension kwargs
    backend_extension_kwargs = deepcopy(genn_extension_kwargs)

    # Extend any settings specified by backend
    for n, v in kwargs.items():
        backend_extension_kwargs[n].extend(v)

    # Add backend include directory to both SWIG and C++ compiler options
    backend_include_dir = os.path.join(genn_path, "include", "genn", "backends", module_stem)
    backend_extension_kwargs["libraries"].insert(0, "genn_" + module_stem + "_backend" + genn_lib_suffix)
    backend_extension_kwargs["include_dirs"].append(backend_include_dir)

    # Add extension to list
    ext_modules.append(Pybind11Extension(module_stem + "_backend", 
                                         [os.path.join(pygenn_src, source_stem + "Backend.cc")],
                                         **backend_extension_kwargs))

class BuildGeNNExt(build_ext):
    def copy_extensions_to_source(self):
        # Search for bits of GeNN built during this process
        files = glob(os.path.join(genn_path, self.build_lib, "pygenn",
                                   f"*{genn_lib_suffix}.*" if WIN else f"libgenn*{genn_lib_suffix}.so"))

        # Copy into source directory
        for f in files:
            dst = os.path.join(pygenn_path, os.path.basename(f))
            print(f"Copying {f} -> {dst}")
            copyfile(f, dst)

        # Copy extensions to source
        super().copy_extensions_to_source()

    def build_extensions(self):
        # We want to build libraries directly into setuptools build_lib directory so that install_lib.copy_tree copies them to where they belong
        # **NOTE** empty string ensures trailing slash to make MSVC happy
        out_dir = os.path.join(genn_path, self.build_lib, "pygenn", "")
        temp_dir = os.path.join(genn_path, self.build_temp, "")

        # Loop through extensions
        required_backends = set()
        for e in self.extensions:
            # Add output directory to library directories so GeNN can be found
            e.library_dirs.append(out_dir)

            # Add standard dependencies
            # **YUCK** these need absolute paths so must be done here
            if WIN:
                e.depends.extend([os.path.join(out_dir, "genn" + genn_lib_suffix + ".dll"),
                                  os.path.join(out_dir, "libffi" + genn_lib_suffix + ".dll")])
            # Otherwise
            else:
                e.depends.append(os.path.join(out_dir, "libgenn" + genn_lib_suffix + ".so"))

            # Loop through required libraries and, 
            # if they are a GeNN backend, add to set
            for l in e.libraries:
                if "_backend_" in l:
                    required_backends.add(l)
                    if WIN:
                        e.depends.append(
                            os.path.join(out_dir, "genn_" + l + genn_lib_suffix + ".dll"))
                    else:
                        e.depends.append(
                            os.path.join(out_dir, "libgenn_" + l + genn_lib_suffix + ".so"))
            print(e.name, e.depends)

        # Loop through required backends
        for b in required_backends:
            # Remove extension from backend name
            backend_title = os.path.splitext(b)[0]

            # Check that backend title ends with configuration
            # and starts with genn_
            assert backend_title.endswith(genn_lib_suffix)
            assert backend_title.startswith("genn_")

            # Slice out name of target and add to list
            target = backend_title[5:-len(genn_lib_suffix)]

            # If compiler is MSVC
            if self.compiler.compiler_type == "msvc":
                check_call(["msbuild", "genn.sln", f"/t:{target}",
                            f"/p:Configuration={genn_lib_suffix[1:]}",
                            "/m", "/verbosity:quiet",
                            f"/p:OutDir={out_dir}",
                            f"/p:IntermediateDirectory={temp_dir}"],
                           cwd=genn_path)
            else:
                # Define make arguments
                make_arguments = ["make", target, "DYNAMIC=1",
                                  f"LIBRARY_DIRECTORY={out_dir}",
                                  f"OBJECT_DIRECTORY={temp_dir}",
                                  f"--jobs={cpu_count(logical=False)}"]
                if debug_build:
                    make_arguments.append("DEBUG=1")

                if coverage_build:
                    make_arguments.append("COVERAGE=1")

                # Build
                check_call(make_arguments, cwd=genn_path)

        super().build_extensions()

# Read version from txt file
with open(os.path.join(genn_path, "version.txt")) as version_file:
    version = version_file.read().strip()

setup(
    name="pygenn",
    version=version,
    packages = find_packages(),
    package_data={"pygenn": package_data},

    url="https://github.com/genn_team/genn",
    ext_package="pygenn",
    ext_modules=ext_modules,
    cmdclass={"build_ext": BuildGeNNExt},
    zip_safe=False,
    python_requires=">=3.6",
    setup_requires=["pybind11", "psutil"],
    install_requires=["numpy>=1.17", "deprecated", "psutil",
                      "importlib-metadata>=1.0;python_version<'3.8'"])
