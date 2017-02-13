#!/bin/bash

# display genn-buildmodel.sh help
genn_help () {
    echo "genn-buildmodel.sh script usage:"
    echo "genn-buildmodel.sh [cdho] model"
    echo "-c            only generate simulation code for the CPU"
    echo "-d            enables the debugging mode"
    echo "-h            shows this help message"
    echo "-o outpath    changes the output directory"
}

# handle script errors
genn_error () { # $1=line, $2=code, $3=message
    echo "genn-buildmodel.sh:$1: error $2: $3"
    exit "$2"
}
trap 'genn_error $LINENO 50 "command failure"' ERR

# parse command options
OUT_PATH="$PWD";
while [[ -n "${!OPTIND}" ]]; do
    while getopts "cdo:h" option; do
    case $option in
        c) CPU_ONLY=1;;
        d) DEBUG=1;;
        h) genn_help; exit;;
        o) OUT_PATH="$OPTARG";;
        ?) genn_help; exit;;
    esac
    done
    if [[ $OPTIND > $# ]]; then break; fi
    MODEL="${!OPTIND}"
    let OPTIND++
done

# command options logic
if [[ -z "$GENN_PATH" ]]; then
    if [[ $(uname -s) == "Linux" ]]; then
        echo "GENN_PATH is not defined - trying to auto-detect"
        export GENN_PATH="$(readlink -f $(dirname $0)/../..)"
    else
        genn_error $LINENO 1 "GENN_PATH is not defined"
    fi
fi
if [[ -z "$MODEL" ]]; then
    genn_error $LINENO 2 "no model file given"
fi
pushd $OUT_PATH > /dev/null
OUT_PATH="$PWD"
popd > /dev/null
pushd $(dirname $MODEL) > /dev/null
MACROS="MODEL=$PWD/$(basename $MODEL) GENERATEALL_PATH=$OUT_PATH"
popd > /dev/null
if [[ -n "$DEBUG" ]]; then
    MACROS="$MACROS DEBUG=1";
fi
if [[ -n "$CPU_ONLY" ]]; then
    MACROS="$MACROS CPU_ONLY=1";
    GENERATEALL=./generateALL_CPU_ONLY
else
    GENERATEALL=./generateALL
fi

# generate model code
make -f "$GENN_PATH/lib/GNUmakefile" $MACROS
# The following became necessary because from Mac OSX El Capitan, SIP (System Integrity Protection) squashes DYLD_LIBRARY_PATH in sub-shells and libcudart.8.dylib has a @rpath based install path which necessitates to add the cuda path to DYLD_LIBRARY_PATH.
unamestr=`uname`
# if [[ "$unamestr" == "Darwin" ]]; then
#     export DYLD_LIBRARY_PATH=$DYLD_LIBRARY_PATH:$CUDA_PATH/lib
# fi
# end of workaround
if [[ -n "$DEBUG" ]]; then
    gdb -tui --args "$GENERATEALL" "$OUT_PATH"
else
    "$GENERATEALL" "$OUT_PATH"
fi

echo "model build complete"
