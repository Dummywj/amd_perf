.PHONY: all configure build run results clean list-payloads ops-build ops-correctness

CMAKE ?= cmake
BUILD_DIR ?= build
CONFIG ?= Release
JOBS ?= $(shell nproc)
CPU ?= 0
NUMA_NODE ?= 0
PAYLOAD ?= smoke

RESULTS_DIR ?= results

VALID_PAYLOADS := smoke fma-register-peak fp32-fma-length-sweep reduce-fp32 gather-fp32 scatter-fp32 softmax-fp32

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
else ifeq ($(PAYLOAD),reduce-fp32)
OPS_PAYLOAD := 1
BENCH_TARGET := reduce_fp32_bench
BENCH_BIN := $(BUILD_DIR)/reduce_fp32_bench
RESULT_JSON := $(RESULTS_DIR)/reduce_fp32.json
REPORT_MD := $(RESULTS_DIR)/reduce_fp32.md
PLOT_SVG := $(RESULTS_DIR)/reduce_fp32.svg
else ifeq ($(PAYLOAD),gather-fp32)
OPS_PAYLOAD := 1
BENCH_TARGET := gather_fp32_bench
BENCH_BIN := $(BUILD_DIR)/gather_fp32_bench
RESULT_JSON := $(RESULTS_DIR)/gather_fp32.json
REPORT_MD := $(RESULTS_DIR)/gather_fp32.md
PLOT_SVG := $(RESULTS_DIR)/gather_fp32.svg
else ifeq ($(PAYLOAD),scatter-fp32)
OPS_PAYLOAD := 1
BENCH_TARGET := scatter_fp32_bench
BENCH_BIN := $(BUILD_DIR)/scatter_fp32_bench
RESULT_JSON := $(RESULTS_DIR)/scatter_fp32.json
REPORT_MD := $(RESULTS_DIR)/scatter_fp32.md
PLOT_SVG := $(RESULTS_DIR)/scatter_fp32.svg
else ifeq ($(PAYLOAD),softmax-fp32)
OPS_PAYLOAD := 1
BENCH_TARGET := softmax_fp32_bench
BENCH_BIN := $(BUILD_DIR)/softmax_fp32_bench
RESULT_JSON := $(RESULTS_DIR)/softmax_fp32.json
REPORT_MD := $(RESULTS_DIR)/softmax_fp32.md
PLOT_SVG := $(RESULTS_DIR)/softmax_fp32.svg
else
$(error unknown PAYLOAD '$(PAYLOAD)'; valid values: $(VALID_PAYLOADS))
endif

all: run

configure:
	$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CONFIG)

build: configure
	$(CMAKE) --build $(BUILD_DIR) --target $(BENCH_TARGET) -j $(JOBS)

ops-build: configure
	$(CMAKE) --build $(BUILD_DIR) --target ops_fp32_correctness reduce_fp32_bench gather_fp32_bench scatter_fp32_bench softmax_fp32_bench -j $(JOBS)

ops-correctness: ops-build results
	$(BUILD_DIR)/ops_fp32_correctness $(RESULTS_DIR)/correctness.md

run: build results
ifeq ($(OPS_PAYLOAD),1)
	numactl --physcpubind=$(CPU) --membind=$(NUMA_NODE) $(BENCH_BIN) \
		--benchmark_min_time=0.25s \
		--benchmark_repetitions=7 \
		--benchmark_enable_random_interleaving=true \
		--benchmark_out=$(RESULT_JSON) \
		--benchmark_out_format=json
else
	taskset -c $(CPU) $(BENCH_BIN)
	taskset -c $(CPU) $(BENCH_BIN) --benchmark_format=json --benchmark_out=$(RESULT_JSON)
endif
	python3 scripts/gbench_json_to_md.py $(RESULT_JSON) $(REPORT_MD)
ifneq ($(filter $(PAYLOAD),fp32-fma-length-sweep fp32_fma_length_sweep),)
	python3 scripts/plot_fma_length_sweep.py $(RESULT_JSON) $(PLOT_SVG)
else ifneq ($(filter $(PAYLOAD),reduce-fp32 gather-fp32 scatter-fp32 softmax-fp32),)
	python3 scripts/ops_report.py $(RESULT_JSON) $(REPORT_MD) $(PLOT_SVG) --dense
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
