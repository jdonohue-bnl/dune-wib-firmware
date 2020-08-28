#include <configs/xilinx_zynqmp.h>
//#include <configs/platform-auto.h>

#define CONFIG_USB 
#define CONFIG_DM_USB
#define CONFIG_DM_USB_GADGET

#define CONFIG_USB_STORAGE
#define CONFIG_USB_GADGET
#define CONFIG_USB_GADGET_MANUFACTURER "U-Boot"
#define CONFIG_USB_GADGET_VENDOR_NUM 0x0
#define CONFIG_USB_GADGET_PRODUCT_NUM 0x0
#define CONFIG_USB_GADGET_VBUS_DRAW 2
#define CONFIG_USB_GADGET_DOWNLOAD

#define CONFIG_USB_DWC3
#define CONFIG_USB_DWC3_GADGET
