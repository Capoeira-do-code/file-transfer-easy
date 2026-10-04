#import <Cocoa/Cocoa.h>
#include <assert.h>

static NSArray<NSString *> *received;
static int lastAction;
void fteTrayAction(int action) { lastAction = action; }
void fteTrayDrop(char *payload) {
    NSData *data = [[NSString stringWithUTF8String:payload] dataUsingEncoding:NSUTF8StringEncoding];
    received = [[NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] copy];
}
#include "../tray_native_darwin.m"

@interface FTEDragFixture : NSObject
@property(retain) NSPasteboard *draggingPasteboard;
@property NSDragOperation draggingSourceOperationMask;
@end
@implementation FTEDragFixture
@end

int main(void) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        NSPasteboard *board = [NSPasteboard pasteboardWithUniqueName];
        NSString *root = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
        NSFileManager *files = NSFileManager.defaultManager;
        assert([files createDirectoryAtPath:root withIntermediateDirectories:YES attributes:nil error:NULL]);
        NSArray<NSString *> *paths = @[[root stringByAppendingPathComponent:@"nota con ñ y \"comillas\".txt"],
            [root stringByAppendingPathComponent:@"Carpeta de prueba"]];
        assert([files createFileAtPath:paths[0] contents:[@"Prueba" dataUsingEncoding:NSUTF8StringEncoding] attributes:nil]);
        assert([files createDirectoryAtPath:paths[1] withIntermediateDirectories:NO attributes:nil error:NULL]);
        [board writeObjects:@[[NSURL fileURLWithPath:paths[0]], [NSURL fileURLWithPath:paths[1] isDirectory:YES],
            [NSURL URLWithString:@"https://example.com/archivo"]]];
        FTEDragFixture *fixture = [[[FTEDragFixture alloc] init] autorelease];
        fixture.draggingPasteboard = board;
        fixture.draggingSourceOperationMask = NSDragOperationCopy;
        id<NSDraggingInfo> drag = (id<NSDraggingInfo>)fixture;
        FTETrayDropView *view = [[[FTETrayDropView alloc] initWithFrame:NSMakeRect(0, 0, 24, 24)] autorelease];
        assert([view draggingEntered:drag] == NSDragOperationCopy);
        assert([view prepareForDragOperation:drag]);
        assert([view performDragOperation:drag]);
        assert(received.count == paths.count);
        // File URLs use decomposed Unicode on macOS. Compare canonically while
        // preserving the paths supplied by AppKit in the application callback.
        for (NSUInteger i = 0; i < paths.count; i++) {
            assert([[received[i] precomposedStringWithCanonicalMapping] isEqualToString:paths[i]]);
            assert([files fileExistsAtPath:received[i]]);
        }
        [received release]; received = nil;

        fixture.draggingSourceOperationMask = NSDragOperationMove;
        assert([view draggingEntered:drag] == NSDragOperationNone);
        assert(![view performDragOperation:drag]);
        assert(received == nil);
        [board clearContents];
        [board writeObjects:@[@"Texto sin archivos"]];
        fixture.draggingSourceOperationMask = NSDragOperationCopy;
        assert([view draggingEntered:drag] == NSDragOperationNone);
        assert(![view performDragOperation:drag]);
        [board releaseGlobally];
        assert([files removeItemAtPath:root error:NULL]);
        puts("PASS native tray file/folder URLs, Unicode and rejected non-file/move drops");

        controller = [[FTETrayController alloc] init];
        NSMenu *menu = [[[NSMenu alloc] initWithTitle:@"Test"] autorelease];
        addAction(menu, @"Abrir ventana", 1);
        [menu performActionForItemAtIndex:0];
        assert(lastAction == 1);
        [controller release]; controller = nil;
        puts("PASS native tray menu dispatch");
    }
    return 0;
}
