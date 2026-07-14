rm(list=ls())

#set working directory to current folder
curr.dir<-dirname(rstudioapi::getActiveDocumentContext()$path)
setwd(curr.dir)

#set result directory
output_dir <- "mod-eval-mod41"
if (!file.exists(output_dir)) {dir.create (output_dir)}

#load needed packages
library(tidyverse)
library(ggpubr)
library(GGally)
library(lattice)
library(ggpmisc)
library(patchwork)
library(EnvStats) # create colors
library(ggsci)
library(RColorBrewer) # create colors

colors<-pal_npg("nrc")(6)


#----------------GOF for PK---------------####
library(RColorBrewer)
colors<-brewer.pal(name="Dark2",8)
# location of DATA Export
run_dir  <- "./run41.dir1/NM_run1/"

# model index
mod_index <- 41

# table names
sdtab_name <- paste0(run_dir,"sdtab",mod_index)


#read data of table sdtab
sdtab <- read.table(sdtab_name, skip = 1, header = TRUE, stringsAsFactors = F)%>%
  filter(MDV != 1) %>%
  mutate(STUDY=case_when(STUDY==1~"0.3 mg/kg",
                         STUDY==2~"1.0 mg/kg",
                         STUDY==3~"3.0 mg/kg",
                         STUDY==4~"6.0 mg/kg",
                         STUDY==5~"10.0 mg/kg",
                         STUDY==6~"15.0 mg/kg"))

pl1 <- ggplot(sdtab, aes(x=IPRED, y=DV, group=ID, color=STUDY)) +
  #geom_line(color="#496C88", size=0.5) +
  geom_point(shape=16, size=2) +
  scale_color_manual(values = colors)+
  scale_x_continuous("Individual predictions (ng/mL)") +
  scale_y_continuous("Observations (ng/mL)") + 
  geom_abline(intercept = 0, slope = 1, size=1.3, color="black") + 
  geom_smooth(inherit.aes = F, data = sdtab, mapping = aes(x=IPRED, y=DV),
              method = "loess", se = FALSE, span=1,
              color="red", size=2, linetype = "dashed")+
  theme_bw(base_size = 30) +
  theme(panel.grid = element_blank(),legend.position = "none") +
  labs(title = "A)")
plot(pl1)
#draw DV-PRED 
pl2 <- ggplot(sdtab, aes(x=PRED, y=DV, group=ID, color=STUDY)) +
  #geom_line(size=0.5) +
  geom_point(shape=16, size=2) +
  scale_color_manual(values = colors)+
  scale_x_continuous("Population predictions (ng/mL)") +
  scale_y_continuous("Observations (ng/mL)") + 
  geom_abline(intercept = 0, slope = 1, size=1.3, color="black") + 
  geom_smooth(inherit.aes = F, data = sdtab, mapping = aes(x=PRED, y=DV),
              method = "loess", se = FALSE, span=1,
              color="red", size=2, linetype = "dashed")+
  theme_bw(base_size = 30) +
  theme(panel.grid = element_blank(),legend.position = "none")+
  labs(color="Study",title = "B)")
plot(pl2)
#draw CWRES_Time
pl3 <- ggplot(sdtab, aes(x=TIME, y=CWRES, group=ID, color=STUDY)) +
  #geom_line(color="#496C88", size=0.5) +
  geom_point(shape=16, size=2) +
  scale_color_manual(values = colors)+
  scale_x_continuous("Time(h)") +
  scale_y_continuous("Conditional weighted residuals\n") +
  geom_abline(intercept = 0, slope = 0, size=1.3, color="black") + 
  geom_smooth(inherit.aes = F, data = sdtab, mapping = aes(x=TIME, y=CWRES),
              method = "loess", se = FALSE, span=1.5, 
              color="red", size=2, linetype = "dashed")+
  theme_bw(base_size = 30) +
  theme(panel.grid = element_blank(),legend.position = "none") +
  labs(title = "C)")
plot(pl3)
#draw CWRES-PRED
pl4 <- ggplot(sdtab, aes(x=PRED, y=CWRES, group=ID, color=STUDY)) +
  #geom_line(color="#496C88", size=0.5) +
  geom_point(shape=16, size=2) +
  scale_color_manual(values = colors)+
  scale_x_continuous("Population predictions (ng/mL)") +
  scale_y_continuous("Conditional weighted residuals\n") + 
  geom_abline(intercept = 0, slope = 0, size=1.3, color="black") + 
  geom_smooth(inherit.aes = F, data = sdtab, mapping = aes(x=PRED, y=CWRES),
              method = "loess", se = FALSE, span=1,
              color="red", size=2, linetype = "dashed")+
  theme_bw(base_size = 30) +
  theme(panel.grid = element_blank(),legend.position = "none") +
  labs(title = "D)")
plot(pl4)

#draw CWRES_Time
pl5 <- ggplot(sdtab, aes(x=IPRED, y=abs(CIWRES), color=STUDY)) +
  geom_point(shape=16, size=2) +
  scale_color_manual(values = colors)+
  scale_x_continuous("Individual predictions") +
  scale_y_continuous("|IWRES|\n", breaks = c(0,0.5,1,1.5,2,2.5)) +
  theme_bw(base_size = 30) +
  theme(panel.grid = element_blank(),legend.position = "none") +
  geom_smooth(formula = y ~ x, method = "loess", linetype="dashed",
              color="red", se = FALSE, span=1, size=2)
plot(pl5)

#draw CWRES's QQ plot
pl6 <- ggplot(sdtab, aes(sample=CWRES)) +
  geom_qq(size=2,color="darkblue",alpha=0.8) +
  geom_qq_line() +
  scale_x_continuous("Quantiles of normal") +
  scale_y_continuous("Conditional weighted residuals\n") +
  theme_bw(base_size = 30) +
  theme(panel.grid = element_blank())
plot(pl6)

#merge
pic <- ggarrange(pl1,pl2,pl3,pl4,pl5,pl6,
                 ncol = 2, nrow = 3, common.legend = T)
plot(pic)

jpeg(filename = paste0(output_dir, "/GOF_mod41.jpg"),width = 8000, height = 12000,res=400)
print(pic)
dev.off()  

