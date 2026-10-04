#include <stdbool.h>
#include <stddef.h>

void fteTrayCreate(const void *bytes, size_t length);
void fteTrayUpdate(const char *content, const char *activity, bool copy, bool open, bool stop);
