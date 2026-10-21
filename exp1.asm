LIST p=16f877a   
    INCLUDE "p16f877a.inc"  
    __CONFIG h'3F31'            

sayi1   equ 0x20
sayi2   equ 0x21
sayi3   equ 0xA0

    org 0x00           
    movlw   b'00000000'
    movwf   STATUS              
    banksel sayi1
    clrf    sayi1
    clrf    sayi2
    banksel PORTD
    clrf    PORTD
    movlw   b'10001000'     
    
    
    movwf   sayi1
    movlw   h'55'               
    movwf   sayi2
    addwf   sayi1, W 
    banksel sayi3
    clrf    sayi3
    movwf   sayi3               
    banksel TRISD
    clrf    TRISD               
    banksel sayi3
    movf    sayi3, W
    banksel PORTD
    movwf   PORTD     
    goto    $-21   
    END