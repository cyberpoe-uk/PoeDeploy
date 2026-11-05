/* Eww's GTK window hosts the same PoeDash surface as the standalone backend.
 * No global input hooks, synthetic events, or separate editor implementation. */
#include <gtk/gtk.h>
#include <Python.h>
#include <pygobject.h>
#include <dlfcn.h>

static gboolean find_host(gpointer unused);
static void host_destroyed(GtkWidget *widget, gpointer unused) {
    (void)widget; (void)unused;
    g_timeout_add(100, find_host, NULL);
}
static GtkWidget *locate(GtkWidget *widget) {
    if (gtk_style_context_has_class(gtk_widget_get_style_context(widget), "poedash-shared-host")) return widget;
    if (GTK_IS_CONTAINER(widget)) {
        GList *children = gtk_container_get_children(GTK_CONTAINER(widget));
        GtkWidget *result = NULL;
        for (GList *p = children; p && !result; p = p->next) result = locate(GTK_WIDGET(p->data));
        g_list_free(children);
        return result;
    }
    return NULL;
}
static gboolean find_host(gpointer unused) {
    (void)unused;
    GtkWidget *host = NULL;
    GList *windows = gtk_window_list_toplevels();
    for (GList *p = windows; p && !host; p = p->next) host = locate(GTK_WIDGET(p->data));
    g_list_free(windows);
    if (!host) return G_SOURCE_CONTINUE;
    if (g_object_get_data(G_OBJECT(host), "poedash-attached")) return G_SOURCE_REMOVE;
    g_object_set_data(G_OBJECT(host), "poedash-attached", GINT_TO_POINTER(1));
    g_signal_connect(host, "destroy", G_CALLBACK(host_destroyed), NULL);
    /* Python extensions require libpython's symbols in the global namespace. */
    if (!dlopen(POEDASH_PYTHON_LIBRARY, RTLD_NOW | RTLD_GLOBAL)) {
        g_warning("PoeDash could not load its Python runtime: %s", dlerror());
        return G_SOURCE_REMOVE;
    }
    if (!Py_IsInitialized()) { Py_Initialize(); PyEval_SaveThread(); }
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *module = NULL, *function = NULL, *wrapper = NULL, *result = NULL;
    PyObject *path = PySys_GetObject("path");
    gchar *scripts = g_build_filename(g_getenv("POEDASH_ROOT"), "scripts", NULL);
    PyObject *entry = PyUnicode_FromString(scripts);
    if (entry) { PyList_Insert(path, 0, entry); Py_DECREF(entry); }
    g_free(scripts);
    module = PyImport_ImportModule("eww_embed");
    if (module && pygobject_init(-1, -1, -1)) {
        function = PyObject_GetAttrString(module, "attach");
        wrapper = pygobject_new(G_OBJECT(host));
        if (function && wrapper) result = PyObject_CallFunctionObjArgs(function, wrapper, NULL);
    }
    if (!result) {
        PyErr_Print();
        GtkWidget *message = gtk_label_new("PoeDash could not initialise. See the startup log and run poedash doctor.");
        gtk_container_add(GTK_CONTAINER(host), message);
        gtk_widget_show(message);
    }
    Py_XDECREF(result); Py_XDECREF(wrapper); Py_XDECREF(function); Py_XDECREF(module);
    PyGILState_Release(gil);
    return G_SOURCE_REMOVE;
}
G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv) {
    (void)argc; (void)argv;
    const gchar *root = g_getenv("POEDASH_ROOT");
    if (!root || !g_path_is_absolute(root)) return;
    g_timeout_add(50, find_host, NULL);
}
