# =================================================================
# PopPK 通用 VPC 绘图引擎 (V1.0)
# =================================================================
library(tidyverse)
library(jsonlite)

args <- commandArgs(trailingOnly = TRUE)
mod_index <- if(length(args) > 0) args[1] else "41"

# 1. 加载配置
config <- fromJSON("project_config.json")
# PsN 默认生成的文件夹和结果文件名
vpc_folder <- paste0("vpc_dir_", mod_index)
vpc_file <- file.path(vpc_folder, "vpc_results.csv")

if (!file.exists(vpc_file)) {
  stop(paste0("❌ 找不到 VPC 结果文件: ", vpc_file, "。请确认 PsN 是否运行成功。"))
}

# 2. 读取数据 (PsN 输出的 csv)
vpc_data <- read.csv(vpc_file, header = TRUE, stringsAsFactors = FALSE)

# 3. 绘图逻辑
# 注意：PsN 的 vpc_results.csv 包含观测值的百分位数和模拟值的置信区间
p_vpc <- ggplot(vpc_data, aes(x = bin_mid)) +
  # 模拟值的 95% 置信区间（阴影部分）
  geom_ribbon(aes(ymin = lo_low, ymax = lo_hi), fill = "blue", alpha = 0.2) + # 5th PI
  geom_ribbon(aes(ymin = med_low, ymax = med_hi), fill = "red", alpha = 0.2) + # 50th PI
  geom_ribbon(aes(ymin = hi_low, ymax = hi_hi), fill = "blue", alpha = 0.2) + # 95th PI
  # 模拟值的中位数线（虚线）
  geom_line(aes(y = lo_med), color = "blue", linetype = "dashed", linewidth = 0.8) +
  geom_line(aes(y = med_med), color = "red", linetype = "dashed", linewidth = 0.8) +
  geom_line(aes(y = hi_med), color = "blue", linetype = "dashed", linewidth = 0.8) +
  # 观测值的百分位数线（实线）
  geom_line(aes(y = obs_lo), color = "blue", linewidth = 1.2) +
  geom_line(aes(y = obs_med), color = "red", linewidth = 1.2) +
  geom_line(aes(y = obs_hi), color = "blue", linewidth = 1.2) +
  # 观测散点（可选，根据需要开启）
  # geom_point(aes(y = obs), alpha = 0.3, size = 1) +
  theme_bw(base_size = 18) +
  theme(panel.grid = element_blank()) +
  labs(
    x = config$units$time,
    y = config$units$conc,
    title = paste0("VPC - Run ", mod_index)
  )

# 4. 保存图片
output_name <- paste0("VPC_mod", mod_index, ".jpg")
jpeg(filename = output_name, width = 3000, height = 2000, res = 300)
print(p_vpc)
dev.off()

message(paste0(">>> VPC 图已生成: ", output_name))
