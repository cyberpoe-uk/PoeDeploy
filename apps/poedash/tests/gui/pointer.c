#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <wayland-client.h>
#include "virtual-pointer.h"
static struct zwlr_virtual_pointer_manager_v1 *manager;
static void global(void *data, struct wl_registry *registry, uint32_t name,const char *interface,uint32_t version) {
 if(!strcmp(interface,"zwlr_virtual_pointer_manager_v1")) manager=wl_registry_bind(registry,name,&zwlr_virtual_pointer_manager_v1_interface,1);
}
static void gone(void *data, struct wl_registry *registry,uint32_t name) {}
static const struct wl_registry_listener listener={global,gone};
static uint32_t stamp(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec*1000+t.tv_nsec/1000000;}
int main(void) {
 struct wl_display *display=wl_display_connect(NULL);if(!display)return 2;
 struct wl_registry *registry=wl_display_get_registry(display);wl_registry_add_listener(registry,&listener,NULL);wl_display_roundtrip(display);if(!manager)return 3;
 struct zwlr_virtual_pointer_v1 *pointer=zwlr_virtual_pointer_manager_v1_create_virtual_pointer(manager,NULL);
 char line[100];unsigned x,y,w,h;
 while(fgets(line,sizeof(line),stdin)) {
  if(sscanf(line,"m %u %u %u %u",&x,&y,&w,&h)==4)zwlr_virtual_pointer_v1_motion_absolute(pointer,stamp(),x,y,w,h);
  else if(line[0]=='d')zwlr_virtual_pointer_v1_button(pointer,stamp(),272,WL_POINTER_BUTTON_STATE_PRESSED);
  else if(line[0]=='u')zwlr_virtual_pointer_v1_button(pointer,stamp(),272,WL_POINTER_BUTTON_STATE_RELEASED);
  else if(line[0]=='q')break;
  zwlr_virtual_pointer_v1_frame(pointer);wl_display_roundtrip(display);puts("ok");fflush(stdout);
 }
 zwlr_virtual_pointer_v1_destroy(pointer);wl_display_flush(display);wl_display_disconnect(display);return 0;
}
