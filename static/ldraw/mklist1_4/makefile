CC=gcc

CFLAGS=-ggdb -DWINDOWS -DHAVE_MEMMOVE -DHAVE_GCC

AR = ar
RANLIB = ranlib

SRCS = mklist.c 
OBJS = $(SRCS:.c=.o)

all	: mklist

mklist	: $(OBJS)
	$(CC) $(CFLAGS) -o mklist $(OBJS)


