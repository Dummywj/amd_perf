#include <benchmark/benchmark.h>
#include <cpuid.h>

#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>

namespace {

std::uint64_t ReadSize(const std::filesystem::path& path) {
  std::ifstream input(path);
  std::string value;
  input >> value;
  if (value.empty()) {
    return 0;
  }
  std::uint64_t multiplier = 1;
  const char suffix = value.back();
  if (suffix == 'K') {
    multiplier = 1024;
    value.pop_back();
  } else if (suffix == 'M') {
    multiplier = 1024 * 1024;
    value.pop_back();
  }
  return std::stoull(value) * multiplier;
}

std::uint64_t ReadInteger(const std::filesystem::path& path) {
  std::ifstream input(path);
  std::uint64_t value = 0;
  input >> value;
  return value;
}

std::uint64_t CountCpuList(const std::filesystem::path& path) {
  std::ifstream input(path);
  std::string list;
  input >> list;
  std::uint64_t count = 0;
  std::size_t begin = 0;
  while (begin < list.size()) {
    const std::size_t comma = list.find(',', begin);
    const std::string range = list.substr(begin, comma - begin);
    const std::size_t dash = range.find('-');
    if (dash == std::string::npos) {
      ++count;
    } else {
      const auto first = std::stoull(range.substr(0, dash));
      const auto last = std::stoull(range.substr(dash + 1));
      count += last - first + 1;
    }
    if (comma == std::string::npos) {
      break;
    }
    begin = comma + 1;
  }
  return count;
}

void BM_StaticInventory(benchmark::State& state) {
  for (auto _ : state) {
    benchmark::DoNotOptimize(_);
  }

  unsigned eax = 0;
  unsigned ebx = 0;
  unsigned ecx = 0;
  unsigned edx = 0;
  __get_cpuid(1, &eax, &ebx, &ecx, &edx);
  const unsigned stepping = eax & 0xf;
  const unsigned base_model = (eax >> 4) & 0xf;
  const unsigned base_family = (eax >> 8) & 0xf;
  const unsigned ext_model = (eax >> 16) & 0xf;
  const unsigned ext_family = (eax >> 20) & 0xff;
  const unsigned family =
      base_family == 0xf ? base_family + ext_family : base_family;
  const unsigned model = base_model | (ext_model << 4);

  state.counters["cpu_family"] = family;
  state.counters["cpu_model"] = model;
  state.counters["cpu_stepping"] = stepping;
  state.counters["max_vector_bits"] = 512;
  state.counters["zmm_registers"] = 32;

  unsigned leaf7_eax = 0;
  unsigned leaf7_ebx = 0;
  unsigned leaf7_ecx = 0;
  unsigned leaf7_edx = 0;
  __get_cpuid_count(7, 0, &leaf7_eax, &leaf7_ebx, &leaf7_ecx, &leaf7_edx);
  unsigned leaf71_eax = 0;
  unsigned leaf71_ebx = 0;
  unsigned leaf71_ecx = 0;
  unsigned leaf71_edx = 0;
  __get_cpuid_count(7, 1, &leaf71_eax, &leaf71_ebx, &leaf71_ecx,
                    &leaf71_edx);
  state.counters["feature_fma"] = (ecx >> 12) & 1U;
  state.counters["feature_avx2"] = (leaf7_ebx >> 5) & 1U;
  state.counters["feature_avx512f"] = (leaf7_ebx >> 16) & 1U;
  state.counters["feature_avx512dq"] = (leaf7_ebx >> 17) & 1U;
  state.counters["feature_avx512bw"] = (leaf7_ebx >> 30) & 1U;
  state.counters["feature_avx512vl"] = (leaf7_ebx >> 31) & 1U;
  state.counters["feature_avx512_vnni"] = (leaf7_ecx >> 11) & 1U;
  state.counters["feature_avx512_bf16"] = (leaf71_eax >> 5) & 1U;

  const std::filesystem::path cache_root =
      "/sys/devices/system/cpu/cpu8/cache";
  for (const auto& entry : std::filesystem::directory_iterator(cache_root)) {
    if (!entry.is_directory() ||
        entry.path().filename().string().rfind("index", 0) != 0) {
      continue;
    }
    const auto level = ReadInteger(entry.path() / "level");
    std::ifstream type_input(entry.path() / "type");
    std::string type;
    type_input >> type;
    if (level == 1 && type != "Data") {
      continue;
    }
    const std::string prefix = "l" + std::to_string(level) + "_";
    state.counters[prefix + "size_bytes"] =
        static_cast<double>(ReadSize(entry.path() / "size"));
    state.counters[prefix + "ways"] =
        static_cast<double>(ReadInteger(entry.path() / "ways_of_associativity"));
    state.counters[prefix + "line_bytes"] =
        static_cast<double>(ReadInteger(entry.path() / "coherency_line_size"));
    const auto shared_logical =
        CountCpuList(entry.path() / "shared_cpu_list");
    state.counters[prefix + "shared_logical_cpus"] =
        static_cast<double>(shared_logical);
    state.counters[prefix + "shared_cores"] =
        static_cast<double>(shared_logical / 2);
  }
}

}  // namespace

BENCHMARK(BM_StaticInventory)->Iterations(1);
