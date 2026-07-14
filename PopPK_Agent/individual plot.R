#个体拟合图
library(ggplot2)
library(dplyr)

mydata <- read.delim(file="E:\\JGH\\INB301\\5.PopPK\\1. Monkey\\1. mod\\SDTAB26",skip=1,stringsAsFactors=FALSE,header=T,sep="")
mydata<-mydata[mydata$MDV==0,]


a<-length(unique(mydata$ID))
str(a)
n<-mydata$ID
row<-6
hit<-1*row

#theme
Mythemebox1 <- theme(panel.background = element_rect(fill = "white",color = "black"),
                     panel.grid.major.y = element_blank(),
                     panel.grid.minor.y = element_blank(),
                     panel.grid.minor.x = element_blank(),
                     axis.text = element_text(family="serif",color = "black",size="13"),
                     axis.title.y=element_text(family="serif",color = "black",size="13"),
                     axis.title.x=element_text(family="serif",color = "black",size="13"),
                     plot.title = element_text(family = "serif", color = "black"),
                     axis.text.x = element_text(hjust = 1, vjust = 1))

output_dir <- "E:/JGH/INB301/5.PopPK/1. Monkey/1. mod/DV"
if (!dir.exists(output_dir)) {
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
}
pdf(paste0(output_dir, "/个体拟合1RUN26.pdf"), width = 10, height = hit*1.5)
myplot<-ggplot(mydata, aes(x=TIME))+
  geom_line(aes(y=IPRED),col="#FF4040",lty=1,linewidth=0.5)+
  geom_line(aes(y=PRED), col="#696969",lty=2,linewidth=0.5)+
  geom_point(aes(y=DV), pch=1,size=2)+ #,pch=1
  xlab("Time, h")+ylab("Concentration, mg/L")+
  scale_y_log10()+
  theme_bw(base_size=12)+theme(panel.grid.major=element_blank(),
                               panel.grid.minor=element_blank(),
                               legend.position="none")+
  theme(strip.text=element_text(size=rel(0.8)),
        axis.title.x=element_text(size=15),axis.title.y=element_text(size=15),
        strip.background=element_rect(fill="#F5F5F5"))+
  facet_wrap(~ID, nrow=row)+
  theme_bw()+
  theme(panel.grid.major=element_blank(), #无主网格线
        panel.grid.minor=element_blank())
print(myplot)
dev.off()
