#import <Cocoa/Cocoa.h>
#include "tray_native_darwin.h"

extern void fteTrayAction(int action);
extern void fteTrayDrop(char *payload);

// The overlay handles file drags and forwards normal clicks to the status
// button, preserving AppKit's menu tracking and keyboard accessibility.
@interface FTETrayDropView : NSView
@property(assign) NSStatusBarButton *button;
@end

@implementation FTETrayDropView
- (instancetype)initWithFrame:(NSRect)frame {
    if ((self = [super initWithFrame:frame])) {
        [self registerForDraggedTypes:@[NSPasteboardTypeFileURL]];
        self.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
        self.toolTip = @"Arrastra archivos o carpetas para añadirlos";
    }
    return self;
}
- (BOOL)isAccessibilityElement { return NO; }
- (void)mouseDown:(NSEvent *)event { [self.button mouseDown:event]; }
- (void)rightMouseDown:(NSEvent *)event { [self.button rightMouseDown:event]; }
- (NSArray<NSString *> *)pathsFromPasteboard:(NSPasteboard *)pasteboard {
    NSArray<NSURL *> *urls = [pasteboard readObjectsForClasses:@[NSURL.class]
        options:@{NSPasteboardURLReadingFileURLsOnlyKey: @YES}];
    NSMutableArray<NSString *> *paths = [NSMutableArray array];
    for (NSURL *url in urls) {
        if (url.isFileURL && url.path.length > 0) [paths addObject:url.path.stringByStandardizingPath];
    }
    return paths;
}
- (NSDragOperation)draggingEntered:(id<NSDraggingInfo>)sender {
    BOOL valid = ([sender draggingSourceOperationMask] & NSDragOperationCopy) &&
        [self pathsFromPasteboard:sender.draggingPasteboard].count > 0;
    [self.button highlight:valid];
    return valid ? NSDragOperationCopy : NSDragOperationNone;
}
- (NSDragOperation)draggingUpdated:(id<NSDraggingInfo>)sender { return [self draggingEntered:sender]; }
- (void)draggingExited:(id<NSDraggingInfo>)sender { [self.button highlight:NO]; }
- (BOOL)prepareForDragOperation:(id<NSDraggingInfo>)sender {
    return [self draggingEntered:sender] == NSDragOperationCopy;
}
- (BOOL)performDragOperation:(id<NSDraggingInfo>)sender {
    NSArray<NSString *> *paths = [self pathsFromPasteboard:sender.draggingPasteboard];
    [self.button highlight:NO];
    if (paths.count == 0 || !([sender draggingSourceOperationMask] & NSDragOperationCopy)) return NO;
    NSData *data = [NSJSONSerialization dataWithJSONObject:paths options:0 error:NULL];
    if (!data) return NO;
    NSString *payload = [[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] autorelease];
    fteTrayDrop((char *)payload.UTF8String);
    return YES;
}
- (void)concludeDragOperation:(id<NSDraggingInfo>)sender { [self.button highlight:NO]; }
@end

@interface FTETrayController : NSObject
- (void)activate:(NSMenuItem *)sender;
@end
@implementation FTETrayController
- (void)activate:(NSMenuItem *)sender { fteTrayAction((int)sender.tag); }
@end

static NSStatusItem *item;
static FTETrayController *controller;
static NSMenuItem *contentItem, *activityItem, *copyItem, *openItem, *stopItem;

static NSMenuItem *addAction(NSMenu *menu, NSString *title, NSInteger action) {
    NSMenuItem *entry = [menu addItemWithTitle:title action:@selector(activate:) keyEquivalent:@""];
    entry.target = controller;
    entry.tag = action;
    return entry;
}

void fteTrayCreate(const void *bytes, size_t length) {
    if (item) return;
    controller = [[FTETrayController alloc] init];
    item = [[[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength] retain];
    NSData *data = [NSData dataWithBytes:bytes length:length];
    NSImage *image = [[[NSImage alloc] initWithData:data] autorelease];
    image.size = NSMakeSize(20, 20);
    image.template = YES;
    item.button.image = image;
    item.button.accessibilityLabel = @"File Transfer Easy";
    FTETrayDropView *drop = [[[FTETrayDropView alloc] initWithFrame:item.button.bounds] autorelease];
    drop.button = item.button;
    [item.button addSubview:drop];

    NSMenu *menu = [[[NSMenu alloc] initWithTitle:@"File Transfer Easy"] autorelease];
    menu.autoenablesItems = NO;
    contentItem = [menu addItemWithTitle:@"Sin archivos" action:nil keyEquivalent:@""];
    activityItem = [menu addItemWithTitle:@"Listo" action:nil keyEquivalent:@""];
    contentItem.enabled = activityItem.enabled = NO;
    [menu addItem:NSMenuItem.separatorItem];
    addAction(menu, @"Abrir ventana", 1);
    openItem = addAction(menu, @"Vista pública", 2);
    copyItem = addAction(menu, @"Copiar enlace", 3);
    openItem.enabled = copyItem.enabled = NO;
    [menu addItem:NSMenuItem.separatorItem];
    addAction(menu, @"Añadir archivos…", 4);
    addAction(menu, @"Añadir carpeta…", 5);
    [menu addItem:NSMenuItem.separatorItem];
    stopItem = addAction(menu, @"Dejar de compartir", 6);
    stopItem.enabled = NO;
    addAction(menu, @"Salir", 7);
    item.menu = menu;
}

void fteTrayUpdate(const char *content, const char *activity, bool copy, bool open, bool stop) {
    contentItem.title = [NSString stringWithUTF8String:content];
    activityItem.title = [NSString stringWithUTF8String:activity];
    copyItem.enabled = copy;
    openItem.enabled = open;
    stopItem.enabled = stop;
}
