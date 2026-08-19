NAME := xsai-hpm-smoke
APP_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
XSAI_DIR := $(abspath $(APP_DIR)/../..)

MARCH ?= rv64gcv_zvl128b
MCMODEL := -mcmodel=medany
CC_OPT := -O2
CXXFLAGS += -std=c++20 -O2
INC_DIR += $(XSAI_DIR)/src
SRCS := main.cpp $(XSAI_DIR)/src/perf_counters.cpp

include $(AM_HOME)/Makefile.app
