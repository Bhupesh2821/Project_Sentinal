#import <Cocoa/Cocoa.h>
#include <Python.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/stat.h>

static BOOL validRoot(NSString *root) {
    NSFileManager *fs=[NSFileManager defaultManager];
    return [fs fileExistsAtPath:[root stringByAppendingPathComponent:@"sentinal/application.py"]] &&
           [fs isExecutableFileAtPath:[root stringByAppendingPathComponent:@".venv/bin/python"]];
}
static void fail(NSString *message) {
    [NSApplication sharedApplication];
    NSAlert *alert=[[NSAlert alloc] init];
    alert.messageText=@"SENTINAL could not start";
    alert.informativeText=message;
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
}
int main(int argc, char **argv) {
    @autoreleasepool {
        NSString *bundle=[[NSBundle mainBundle] bundlePath];
        NSString *candidate=[bundle stringByDeletingLastPathComponent];
        NSString *root=nil;
        for (int depth=0;depth<5;depth++) {
            if (validRoot(candidate)) { root=candidate; break; }
            candidate=[candidate stringByDeletingLastPathComponent];
        }
        if (!root) {
            NSDictionary *record=[NSDictionary dictionaryWithContentsOfFile:[[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:@"ProjectRoot.plist"]];
            NSString *saved=record[@"ProjectRoot"];
            if (saved && validRoot(saved)) root=saved;
        }
        if (!root) {
            fail(@"This app uses the existing SENTINAL project and its local Python environment. Keep it with the full project, run install.command once in that project, then reopen SENTINAL. This is not a standalone installer.");
            return 2;
        }
        NSFileManager *fs=[NSFileManager defaultManager];
        NSDictionary *paths=@{
          @"YOLO_CONFIG_DIR":@"config/runtime/ultralytics", @"MPLCONFIGDIR":@"config/runtime/matplotlib",
          @"XDG_CONFIG_HOME":@"config/runtime/xdg", @"XDG_DATA_HOME":@"work/runtime-data",
          @"XDG_CACHE_HOME":@"work/cache/xdg", @"TORCH_HOME":@"work/cache/torch",
          @"PIP_CACHE_DIR":@"work/pip-cache", @"PYTHONPYCACHEPREFIX":@"work/cache/python",
          @"TMPDIR":@"work/tmp", @"TEMP":@"work/tmp", @"TMP":@"work/tmp"};
        for (NSString *key in paths) {
            NSString *path=[root stringByAppendingPathComponent:paths[key]];
            [fs createDirectoryAtPath:path withIntermediateDirectories:YES attributes:nil error:NULL];
            setenv(key.UTF8String,path.fileSystemRepresentation,1);
        }
        setenv("YOLO_AUTOINSTALL","false",1); setenv("YOLO_OFFLINE","true",1);
        setenv("SENTINAL_PROJECT_ROOT",root.fileSystemRepresentation,1);
        setenv("SENTINAL_APP_BUNDLE",bundle.fileSystemRepresentation,1);
        NSString *logs=[root stringByAppendingPathComponent:@"logs"];
        [fs createDirectoryAtPath:logs withIntermediateDirectories:YES attributes:nil error:NULL];
        NSString *log=[logs stringByAppendingPathComponent:@"app-launcher.log"];
        NSDictionary *attributes=[fs attributesOfItemAtPath:log error:NULL];
        if ([attributes fileSize]>1048576) {
            NSString *old=[logs stringByAppendingPathComponent:@"app-launcher.previous.log"];
            [fs removeItemAtPath:old error:NULL]; [fs moveItemAtPath:log toPath:old error:NULL];
        }
        int fd=open(log.fileSystemRepresentation,O_CREAT|O_WRONLY|O_APPEND,0600);
        if (fd>=0) { fchmod(fd,0600);dup2(fd,STDOUT_FILENO);dup2(fd,STDERR_FILENO);close(fd); }
        chdir(root.fileSystemRepresentation);
        PyConfig config;PyConfig_InitIsolatedConfig(&config);
        config.site_import=0;config.parse_argv=0;
        PyStatus status=PyConfig_SetBytesString(&config,&config.home,SENTINAL_PYTHON_HOME);
        if (!PyStatus_Exception(status)) status=PyConfig_SetBytesString(&config,&config.executable,[[root stringByAppendingPathComponent:@".venv/bin/python"] fileSystemRepresentation]);
        if (!PyStatus_Exception(status)) status=PyConfig_SetBytesString(&config,&config.program_name,argv[0]);
        if (!PyStatus_Exception(status)) status=PyConfig_SetBytesString(&config,&config.pycache_prefix,[[root stringByAppendingPathComponent:@"work/cache/python"] fileSystemRepresentation]);
        if (!PyStatus_Exception(status)) status=PyConfig_SetBytesArgv(&config,argc,argv);
        if (!PyStatus_Exception(status)) status=Py_InitializeFromConfig(&config);
        PyConfig_Clear(&config);
        if (PyStatus_Exception(status)) {
            fprintf(stderr,"SENTINAL Python initialization failed: %s\n",status.err_msg?status.err_msg:"unknown");
            fail(@"The project's Python runtime could not initialize. Run install.command and try again. Technical details are in logs/app-launcher.log.");return 2;
        }
        NSString *bootstrap=[[[NSBundle mainBundle] resourcePath] stringByAppendingPathComponent:@"bootstrap.py"];
        FILE *script=fopen(bootstrap.fileSystemRepresentation,"r");
        if (!script) { fail(@"The app bundle is incomplete. Rebuild it from this project's tools/build_macos_app.py.");Py_FinalizeEx();return 2; }
        int result=PyRun_SimpleFileExFlags(script,bootstrap.fileSystemRepresentation,1,NULL);
        if (result) fail(@"The application could not finish startup. Check logs/app-launcher.log and run install.command if dependencies are missing.");
        int final=Py_FinalizeEx();
        return result?2:(final<0?120:0);
    }
}
