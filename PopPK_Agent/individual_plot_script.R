# =================================================================
# PopPK 通用个体拟合图引擎 (V3.1) - 同一路径简化版
# =================================================================
library(ggplot2)
library(dplyr)
library(jsonlite)

args <- commandArgs(trailingOnly = TRUE)
mod_index <- if(length(args) > 0) args[1] else "41"

# 1. 加载配置与数据
if (!file.exists("project_config.json")) stop("❌ 未找到配置文件")
config <- fromJSON("project_config.json")
sdtab_name <- paste0("sdtab", mod_index)

if (!file.exists(sdtab_name)) stop(paste0("❌ 未找到数据：", sdtab_name))
mydata <- read.table(sdtab_name, skip = 1, header = TRUE) %>% filter(MDV == 0)

# 2. 动态布局计算
num_ids <- length(unique(mydata$ID))
pdf_height <- ceiling(num_ids / 2) * 2.5
if(pdf_height < 10) pdf_height <- 10

# 3. 绘图
p_ind <- ggplot(mydata, aes(x=TIME)) +
  geom_line(aes(y=IPRED), color="#FF4040", linetype=1, linewidth=0.6) +
  geom_line(aes(y=PRED), color="#696969", linetype=2, linewidth=0.6) +
  geom_point(aes(y=DV), shape=1, size=2) +
  scale_y_log10() +
  labs(x = config$units$time, y = config$units$conc, title = paste0("Individual Plots - Run ", mod_index)) +
  facet_wrap(~ID, ncol = 2, scales = "free_y") +
  theme_bw(base_size = 12) +
  theme(
    panel.grid.major = element_blank(),
    panel.grid.minor = element_blank(),
    strip.background = element_rect(fill="#F5F5F5"),
    strip.text = element_text(face="bold")
  )

# 4. 保存
# 为了方便你查看，我们也把结果放在一个独立的子文件夹里，或者直接放根目录也行
output_file <- paste0("Individual_Plots_Run", mod_index, ".pdf")
pdf(output_file, width = 10, height = pdf_height)
print(p_ind)
dev.off()

message(paste0(">>> 个体拟合图已生成：", output_file))
