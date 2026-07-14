# =================================================================
# Duxact PopPK 自动化诊断站 - VPC 绘图引擎 V4.3
# 功能：物理级列名去噪 + 原始数据直连 + 剂量组分面对齐 + 直观数字轴
# =================================================================
library(tidyverse)
library(jsonlite)
library(scales)

# --- 1. 物理级列名清洗函数：确保 dplyr 流程不因空列名崩溃 ---
robust_clean_names <- function(df) {
  df <- df[, !is.na(colnames(df)) & colnames(df) != "", drop = FALSE]
  clean_names <- trimws(gsub("[\"\\\n]", "", colnames(df)))
  valid_idx <- which(clean_names != "")
  df <- df[, valid_idx, drop = FALSE]
  colnames(df) <- make.unique(clean_names[valid_idx])
  return(df)
}

# --- 2. 环境准备与配置加载 ---
args <- commandArgs(trailingOnly = TRUE)
mod_index <- if(length(args) > 0) args[1] else "41"
mod_file <- paste0("run", mod_index, ".mod")
vpc_res_path <- file.path(paste0("vpc_dir_", mod_index), "vpc_results.csv")
config_file <- "project_config.json"

if (!file.exists(vpc_res_path)) stop("❌ 找不到结果文件")

proj_cfg <- fromJSON(config_file)
group_factor <- proj_cfg$grouping$factor
group_labels <- proj_cfg$grouping$labels

# --- 3. 解析 .mod 获取原始数据散点 [cite: 110, 118] ---
mod_lines <- readLines(mod_file)
data_line <- mod_lines[grep("(?i)^\\$DATA", mod_lines)][1]
raw_data_path <- str_match(data_line, "(?i)^\\$DATA\\s+([^\\s,]+)")[2]
raw_data_path <- gsub("[\"']", "", raw_data_path)

message(paste0(">>> 🚀 正在读取原始数据集散点: ", raw_data_path))

raw_obs_data <- read.csv(raw_data_path, check.names = FALSE, stringsAsFactors = FALSE)
raw_obs_clean <- robust_clean_names(raw_obs_data) %>%
  mutate(
    TIME_VAL = as.numeric(as.character(!!sym(intersect(colnames(.), c("TIME", "TAD"))[1]))),
    DV_VAL   = as.numeric(as.character(!!sym(intersect(colnames(.), c("DV", "CONC"))[1]))),
    STRAT_ID = as.character(as.numeric(!!sym(group_factor)))
  ) %>%
  filter(!is.na(DV_VAL), DV_VAL > 0) %>%
  mutate(STRAT_LABEL = unlist(group_labels)[STRAT_ID])

# --- 4. 深度解析 vpc_results.csv (统计线) [cite: 110, 114] ---
lines <- readLines(vpc_res_path)
header_indices <- grep("median.idv", lines)
strata_pattern <- paste0("strata\\s+", group_factor, "\\s*=\\s*([0-9.]+)")
strata_indices <- grep(strata_pattern, lines, ignore.case = TRUE)
# 核心修正：锁定第一个诊断信息位置，解决 6 elements 警告
diag_indices <- grep("Diagnostics VPC", lines)
global_end <- if(length(diag_indices) > 0) diag_indices[1] else length(lines)

all_strata_stats <- list()
for (i in seq_along(header_indices)) {
  start_ln <- header_indices[i]
  next_ln <- if (i < length(header_indices)) header_indices[i+1] else global_end

  prev_strata_ln <- tail(strata_indices[strata_indices < start_ln], 1)
  current_id <- if (length(prev_strata_ln) > 0) {
    as.character(as.numeric(str_match(lines[prev_strata_ln], strata_pattern)[2]))
  } else "Overall"

  block <- read.csv(text = lines[start_ln:(next_ln-1)], header = TRUE, check.names = FALSE)
  block <- robust_clean_names(block)

  stratum_clean <- block %>%
    filter(!grepl("median", `median.idv`)) %>%
    transmute(
      bin_mid = as.numeric(`median.idv`),
      obs_med = as.numeric(`50% real`), med_med = as.numeric(`50% sim`),
      med_low = as.numeric(`95%CI for 50% from`), med_hi = as.numeric(`95%CI for 50% to`),
      obs_lo  = as.numeric(`5% real`), lo_med = as.numeric(`5% sim`),
      lo_low  = as.numeric(`95%CI for 5% from`), lo_hi  = as.numeric(`95%CI for 5% to`),
      obs_hi  = as.numeric(`95% real`), hi_med = as.numeric(`95% sim`),
      hi_low  = as.numeric(`95%CI for 95% from`), hi_hi  = as.numeric(`95%CI for 95% to`),
      STRAT_ID = current_id
    ) %>%
    filter(!is.na(bin_mid)) %>%
    mutate(STRAT_LABEL = unlist(group_labels)[STRAT_ID])
  all_strata_stats[[i]] <- stratum_clean
}
vpc_stats <- bind_rows(all_strata_stats)

# --- 5. 绘图 (Log10 + 6 剂量组对齐) ---
p_vpc <- ggplot(vpc_stats, aes(x = bin_mid)) +
  # 阴影层
  geom_ribbon(aes(ymin = hi_low, ymax = hi_hi, fill = "5% & 95% CI (Sim)"), alpha = 0.2) +
  geom_ribbon(aes(ymin = lo_low, ymax = lo_hi, fill = "5% & 95% CI (Sim)"), alpha = 0.2) +
  geom_ribbon(aes(ymin = med_low, ymax = med_hi, fill = "Median CI (Sim)"), alpha = 0.2) +

  # 线条层
  geom_line(aes(y = hi_med, color = "5% & 95% Percentiles (Sim)"), linetype = "dashed", linewidth = 0.7) +
  geom_line(aes(y = lo_med, color = "5% & 95% Percentiles (Sim)"), linetype = "dashed", linewidth = 0.7) +
  geom_line(aes(y = med_med, color = "Median (Sim)"), linetype = "dashed", linewidth = 0.7) +
  geom_line(aes(y = obs_hi, color = "5% & 95% Percentiles (Obs)"), linewidth = 0.8) +
  geom_line(aes(y = obs_lo, color = "5% & 95% Percentiles (Obs)"), linewidth = 0.8) +
  geom_line(aes(y = obs_med, color = "Median (Obs)"), linewidth = 0.8) +

  # 黑色实测散点层 (保留航哥的微调设置)
  geom_point(data = raw_obs_clean, aes(x = TIME_VAL, y = DV_VAL), color = "black", alpha = 0.6, size = 0.8) +

  # 分层显示
  facet_wrap(~STRAT_LABEL, scales = "free", ncol = 2) +

  # --- 核心修正点：解决多重参数冲突并美化标签 [cite: 137] ---
  scale_y_log10(
    breaks = scales::log_breaks(),
    labels = function(x) format(x, scientific = FALSE, trim = TRUE, drop0trailing = TRUE)
  ) +

  scale_color_manual(name = "Percentiles", values = c(
    "Median (Obs)" = "#DD4B39", "Median (Sim)" = "#DD4B39",
    "5% & 95% Percentiles (Obs)" = "#3C8DBC", "5% & 95% Percentiles (Sim)" = "#3C8DBC"
  )) +
  scale_fill_manual(name = "Confidence Intervals", values = c(
    "Median CI (Sim)" = "#DD4B39", "5% & 95% CI (Sim)" = "#3C8DBC"
  )) +
  theme_bw(base_size = 14) +
  theme(legend.position = "bottom", legend.box = "vertical", panel.grid.minor = element_blank()) +
  labs(x = proj_cfg$units$time, y = proj_cfg$units$conc,
       title = paste0("Stratified Log-VPC (Run ", mod_index, ")"))

# 6. 保存
ggsave(paste0("VPC_Stratified_mod", mod_index, ".jpg"), plot = p_vpc, width = 12, height = 9, dpi = 300)
message(">>> ✅ VPC 任务闭环任务圆满成功！")