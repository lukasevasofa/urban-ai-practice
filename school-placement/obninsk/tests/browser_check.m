// Настоящий WebKit с непостоянным профилем. Проверяются только локальная тестовая копия и её страница.
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

@interface BrowserCheck : NSObject <WKNavigationDelegate>
@property(nonatomic) BOOL started;
@property(nonatomic, strong) NSString *script;
@property(nonatomic, strong) NSString *output;
@end

@implementation BrowserCheck
- (void)webView:(WKWebView *)view didFinishNavigation:(WKNavigation *)navigation {
    if (self.started) return;
    self.started = YES;
    [view callAsyncJavaScript:self.script arguments:@{} inFrame:nil inContentWorld:WKContentWorld.pageWorld
        completionHandler:^(id value, NSError *error) {
        NSString *path = [self.output stringByAppendingPathComponent:@"browser_check.json"];
        if (error) {
            NSData *report = [NSJSONSerialization dataWithJSONObject:@{@"status":@"failed", @"error":error.description}
                options:NSJSONWritingPrettyPrinted error:nil];
            [report writeToFile:path atomically:YES];
            NSLog(@"WebKit: %@", error);
            [NSApp terminate:nil];
            return;
        }
        [(NSString *)value writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
        NSLog(@"%@", value);
        [view takeSnapshotWithConfiguration:nil completionHandler:^(NSImage *image, NSError *snapshotError) {
            if (image) {
                NSBitmapImageRep *bitmap = [NSBitmapImageRep imageRepWithData:image.TIFFRepresentation];
                NSData *png = [bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
                [png writeToFile:[self.output stringByAppendingPathComponent:@"browser_preview.png"] atomically:YES];
            } else {
                NSLog(@"Snapshot: %@", snapshotError);
            }
            [NSApp terminate:nil];
        }];
    }];
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) return 2;
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyAccessory];
        WKWebViewConfiguration *configuration = [WKWebViewConfiguration new];
        configuration.websiteDataStore = WKWebsiteDataStore.nonPersistentDataStore;
        WKWebView *view = [[WKWebView alloc] initWithFrame:NSMakeRect(0, 0, 1440, 1800) configuration:configuration];
        NSWindow *window = [[NSWindow alloc] initWithContentRect:view.frame
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
        window.title = @"Проверка Обнинска — изолированная тестовая копия";
        window.contentView = view;
        [window orderFront:nil];
        BrowserCheck *check = [BrowserCheck new];
        check.output = [NSString stringWithUTF8String:argv[2]];
        check.script = [NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]
            encoding:NSUTF8StringEncoding error:nil];
        view.navigationDelegate = check;
        [view loadRequest:[NSURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1:8766"]]];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            NSLog(@"WebKit timeout");
            [NSApp terminate:nil];
        });
        [app run];
        (void)check;
        (void)window;
    }
    return 0;
}
