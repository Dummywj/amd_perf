.PHONY: all configure build run results clean list-payloads

CMAKE ?= cmake
BUILD_DIR ?= build
CONFIG ?= Release
JOBS ?= $(shell nproc)
CPU ?= 0
PAYLOAD ?= smoke

RESULTS_DIR ?= results

VALID_PAYLOADS := smoke fma-register-peak fp32-fma-length-sweep

ifneq ($(filter $(PAYLOAD),smoke gbench_smoke),)
BENCH_TARGET := gbench_smoke
BENCH_BIN := $(BUILD_DIR)/gbench_smoke
RESULT_JSON := $(RESULTS_DIR)/smoke_bench.json
REPORT_MD := $(RESULTS_DIR)/smoke_bench.md
PLOT_SVG :=
else ifneq ($(filter $(PAYLOAD),fma-register-peak fma_register_peak),)
BENCH_TARGET := fma_register_peak_bench
BENCH_BIN := $(BUILD_DIR)/fma_register_peak_bench
RESULT_JSON := $(RESULTS_DIR)/fma_register_peak_bench.json
REPORT_MD := $(RESULTS_DIR)/fma_register_peak_bench.md
PLOT_SVG :=
else ifneq ($(filter $(PAYLOAD),fp32-fma-length-sweep fp32_fma_length_sweep),)
BENCH_TARGET := fp32_fma_length_sweep_bench
BENCH_BIN := $(BUILD_DIR)/fp32_fma_length_sweep_bench
RESULT_JSON := $(RESULTS_DIR)/fp32_fma_length_sweep_bench.json
REPORT_MD := $(RESULTS_DIR)/fp32_fma_length_sweep_bench.md
PLOT_SVG := $(RESULTS_DIR)/fp32_fma_length_sweep_bench.svg
else
$(error unknown PAYLOAD '$(PAYLOAD)'; valid values: $(VALID_PAYLOADS))
endif

all: run

configure:
	$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CONFIG)

build: configure
	$(CMAKE) --build $(BUILD_DIR) --target $(BENCH_TARGET) -j $(JOBS)

run: build results
	taskset -c $(CPU) $(BENCH_BIN)
	taskset -c $(CPU) $(BENCH_BIN) --benchmark_format=json --benchmark_out=$(RESULT_JSON)
	python3 scripts/gbench_json_to_md.py $(RESULT_JSON) $(REPORT_MD)
ifneq ($(PLOT_SVG),)
	python3 scripts/plot_fma_length_sweep.py $(RESULT_JSON) $(PLOT_SVG)
else
	@printf 'plot: PAYLOAD=%s has no plot generator; generated %s and %s\n' "$(PAYLOAD)" "$(RESULT_JSON)" "$(REPORT_MD)"
endif

list-payloads:
	@printf '%s\n' $(VALID_PAYLOADS)

results:
	mkdir -p $(RESULTS_DIR)

clean:
	$(CMAKE) -E rm -rf $(BUILD_DIR)
	$(CMAKE) -E rm -f $(RESULTS_DIR)/*.json $(RESULTS_DIR)/*.csv $(RESULTS_DIR)/*.log $(RESULTS_DIR)/*.md $(RESULTS_DIR)/*.svg
